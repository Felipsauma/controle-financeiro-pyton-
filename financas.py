"""
Núcleo do Controle de Gastos
----------------------------
Tudo o que não é tela fica aqui: salvar e carregar os dados, validar o que
o usuário digita, calcular saldos e totais, orçamentos, categorias,
lançamentos recorrentes e exportação para CSV.

Quem usa este módulo:
  - controle_gastos.py  (versão de terminal)
  - app_gastos.py       (versão com janela)
  - test_financas.py    (testes automáticos)

Formato do arquivo gastos.json:
  {
    "lancamentos": [{"tipo": "despesa", "descricao": "Almoço", "valor": 25.9,
                     "categoria": "Alimentação", "data": "2026-10-15"}, ...],
    "orcamentos":  {"Lazer": 300.0, ...},          # limite mensal por categoria
    "recorrentes": [{"id": "9f2c...", "tipo": "receita", "descricao": "Salário",
                     "valor": 3500.0, "categoria": "Salário", "dia": 5,
                     "ultimo_mes": "2026-10"}, ...],
    "categorias":  {"despesa": ["Alimentação", ...], "receita": ["Salário", ...]},
    "icones":      {"Pets": "🐶", ...},           # ícone escolhido para a categoria
    "contas":      [{"id": "...", "nome": "Nubank", "tipo": "cartao",
                     "fechamento": 3, "vencimento": 10, "limite": 2000.0}, ...],
    "metas":       [{"id": "...", "nome": "Viagem", "alvo": 5000.0,
                     "guardado": 1200.0, "prazo": "2027-07"}, ...],
    "cofrinho":    [{"id": "...", "data": "2026-10-15", "valor": 200.0,   # negativo = retirada
                     "descricao": "Sobra do mês"}, ...]
  }

Campos que um lançamento pode ter além dos básicos:
  "recorrente": id do recorrente que o criou
  "compra":     id da compra parcelada, e "parcela": "3/10"
  "conta":      id da conta ou cartão
  "pendente":   true = conta a pagar que ainda não foi paga

Sobre dinheiro: os valores ficam no arquivo como números com 2 casas, mas
todas as somas são feitas em centavos (números inteiros), para não acumular
os erros de arredondamento do float (0,1 + 0,2 dá exatamente 0,30).
"""

import calendar
import csv
import json
import math
import os
import re
import shutil
import unicodedata
import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

# Arquivo onde os dados são guardados (fica ao lado deste script)
ARQUIVO = Path(__file__).parent / "gastos.json"

TIPOS = ("despesa", "receita")
# Categorias de quem começa do zero; depois cada pessoa pode criar e remover as suas
CATEGORIAS_DESPESA = ["Alimentação", "Transporte", "Moradia", "Lazer", "Saúde", "Educação", "Outros"]
CATEGORIAS_RECEITA = ["Salário", "Freelance", "Investimentos", "Presente", "Outros"]
CATEGORIAS_PADRAO = {"despesa": CATEGORIAS_DESPESA, "receita": CATEGORIAS_RECEITA}
TAMANHO_MAXIMO_CATEGORIA = 30

NOMES_MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
               "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

# A partir de quanto do orçamento usado a categoria entra em "alerta" (80%)
ALERTA_ORCAMENTO = 0.8

# Maior valor aceito num lançamento (evita erros de digitação absurdos)
VALOR_MAXIMO = 1_000_000_000

# Ícones das categorias padrão; as que a pessoa cria ganham o que ela escolher
ICONES_PADRAO = {
    "Alimentação": "🍔", "Transporte": "🚌", "Moradia": "🏠", "Lazer": "🎬", "Saúde": "💊",
    "Educação": "📚", "Outros": "📦", "Salário": "💼", "Freelance": "💻",
    "Investimentos": "📈", "Presente": "🎁",
}
ICONE_GENERICO = "🏷️"
ICONES_PARA_ESCOLHER = ["🏷️", "🐶", "🛒", "☕", "🍺", "👕", "💄", "🎮", "📱", "🌐", "⛽", "🚗",
                        "✈️", "🏋️", "🎓", "👶", "🎵", "📺", "💡", "💧", "🧾", "🏦", "💰", "🪙"]

TIPOS_DE_CONTA = {"corrente": "Conta corrente", "dinheiro": "Dinheiro", "cartao": "Cartão de crédito"}

# Campos que ligam o lançamento a outras coisas e não aparecem no formulário
CAMPOS_DE_LIGACAO = ("recorrente", "compra", "parcela")
CAMPOS_EXTRAS = CAMPOS_DE_LIGACAO + ("conta", "pendente")

MAXIMO_PARCELAS = 48

# Quantos backups diários guardar na pasta "backups"
DIAS_DE_BACKUP = 30


def categorias_do_tipo(dados, tipo):
    return dados["categorias"]["receita" if tipo == "receita" else "despesa"]


def manter_extras(antigo, novo, campos=CAMPOS_EXTRAS):
    """Ao editar, o lançamento novo continua com as ligações do antigo
    (recorrente, parcela, conta...) que o formulário não mostra."""
    for campo in campos:
        if campo in antigo and campo not in novo:
            novo[campo] = antigo[campo]
    return novo


# ----------------------------------------------------------------------
# Salvar e carregar dados
# ----------------------------------------------------------------------

class DadosCorrompidos(Exception):
    """O arquivo de dados não pôde ser lido, inteiro ou em parte.

    - backup:    cópia do arquivo original, para nada se perder.
    - dados:     o que deu para aproveitar (vazio se o arquivo estava ilegível).
    - ignorados: quantos itens inválidos ficaram de fora.
    """

    def __init__(self, backup, dados=None, ignorados=0):
        if ignorados:
            mensagem = (f"{ignorados} item(ns) inválido(s) no arquivo de dados foram ignorados. "
                        f"O arquivo original foi copiado para {backup.name}")
        else:
            mensagem = f"Arquivo de dados corrompido. Uma cópia foi guardada em {backup.name}"
        super().__init__(mensagem)
        self.backup = backup
        self.dados = dados if dados is not None else dados_vazios()
        self.ignorados = ignorados


class DadosAlteradosPorFora(Exception):
    """O arquivo mudou desde que foi carregado (por exemplo, pela outra versão do
    programa aberta ao mesmo tempo). Salvar agora apagaria essas mudanças."""

    def __init__(self):
        super().__init__("Os dados foram alterados por outro programa depois de carregados.")


def dados_vazios():
    return {"lancamentos": [], "orcamentos": {}, "recorrentes": [],
            "categorias": {tipo: list(CATEGORIAS_PADRAO[tipo]) for tipo in TIPOS},
            "icones": {}, "contas": [], "metas": [], "cofrinho": []}


# Como o arquivo estava na última vez que este programa o leu ou gravou:
# {caminho: (data de modificação, tamanho)}. Serve para perceber se outro
# programa mexeu nele no meio do caminho.
_versoes = {}


def _versao(arquivo):
    try:
        info = arquivo.stat()
    except FileNotFoundError:
        return None
    return info.st_mtime_ns, info.st_size


def _lembrar_versao(arquivo):
    _versoes[str(arquivo.resolve())] = _versao(arquivo)


def _nome_backup(arquivo):
    return arquivo.with_name(f"{arquivo.stem}-corrompido-{datetime.now():%Y%m%d-%H%M%S}{arquivo.suffix}")


def _guardar_backup(arquivo):
    """Renomeia o arquivo estragado para que ele nunca seja sobrescrito."""
    backup = _nome_backup(arquivo)
    arquivo.replace(backup)
    _lembrar_versao(arquivo)  # agora o arquivo não existe mais
    raise DadosCorrompidos(backup)


def _numero_valido(valor):
    return (isinstance(valor, (int, float)) and not isinstance(valor, bool)
            and math.isfinite(valor) and 0 < valor <= VALOR_MAXIMO)


def _data_valida(texto):
    try:
        return isinstance(texto, str) and len(texto) == 10 and bool(date.fromisoformat(texto))
    except ValueError:
        return False


def _texto_valido(texto):
    return isinstance(texto, str) and texto.strip() != ""


def _lancamento_valido(item):
    if not isinstance(item, dict):
        return False
    item.setdefault("tipo", "despesa")  # versões antigas só tinham despesas
    return (item["tipo"] in TIPOS and isinstance(item.get("descricao"), str)
            and _numero_valido(item.get("valor")) and _texto_valido(item.get("categoria"))
            and _data_valida(item.get("data")))


def _recorrente_valido(item):
    if not isinstance(item, dict):
        return False
    dia, mes = item.get("dia"), item.get("ultimo_mes")
    return (item.get("tipo") in TIPOS and isinstance(item.get("descricao"), str)
            and _numero_valido(item.get("valor")) and _texto_valido(item.get("categoria"))
            and isinstance(dia, int) and not isinstance(dia, bool) and 1 <= dia <= 31
            and isinstance(mes, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes) is not None)


def _dia_valido(dia):
    return isinstance(dia, int) and not isinstance(dia, bool) and 1 <= dia <= 31


def _conta_valida(item):
    if not isinstance(item, dict):
        return False
    if not (isinstance(item.get("id"), str) and _texto_valido(item.get("nome"))
            and item.get("tipo") in TIPOS_DE_CONTA):
        return False
    if item.get("limite") is not None and not _numero_valido(item["limite"]):
        return False
    return item["tipo"] != "cartao" or (_dia_valido(item.get("fechamento"))
                                        and _dia_valido(item.get("vencimento")))


def _meta_valida(item):
    if not isinstance(item, dict):
        return False
    guardado = item.get("guardado", 0)
    prazo = item.get("prazo")
    return (isinstance(item.get("id"), str) and _texto_valido(item.get("nome"))
            and _numero_valido(item.get("alvo"))
            and isinstance(guardado, (int, float)) and not isinstance(guardado, bool)
            and math.isfinite(guardado) and 0 <= guardado <= VALOR_MAXIMO
            and (prazo is None or (isinstance(prazo, str)
                                   and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", prazo) is not None)))


def _movimento_valido(item):
    if not isinstance(item, dict):
        return False
    valor = item.get("valor")
    return (isinstance(item.get("id"), str) and isinstance(item.get("descricao"), str)
            and _data_valida(item.get("data"))
            and isinstance(valor, (int, float)) and not isinstance(valor, bool)
            and math.isfinite(valor) and valor != 0 and abs(valor) <= VALOR_MAXIMO)


def _ler_conteudo(conteudo):
    """Monta os dados a partir do JSON lido, deixando de fora o que for inválido.

    Retorna (dados, quantos itens foram ignorados).
    """
    dados = dados_vazios()
    ignorados = 0

    for chave, valido in [("lancamentos", _lancamento_valido), ("recorrentes", _recorrente_valido),
                          ("contas", _conta_valida), ("metas", _meta_valida),
                          ("cofrinho", _movimento_valido)]:
        lista = conteudo.get(chave, [])
        if not isinstance(lista, list):
            ignorados += 1
            continue
        for item in lista:
            if valido(item):
                dados[chave].append(item)
            else:
                ignorados += 1

    orcamentos = conteudo.get("orcamentos", {})
    if isinstance(orcamentos, dict):
        for categoria, limite in orcamentos.items():
            if _numero_valido(limite):
                dados["orcamentos"][categoria] = limite
            else:
                ignorados += 1
    else:
        ignorados += 1

    categorias = conteudo.get("categorias")
    if isinstance(categorias, dict):
        for tipo in TIPOS:
            lista = categorias.get(tipo)
            if isinstance(lista, list):
                nomes = [c.strip() for c in lista if _texto_valido(c)]
                if nomes:
                    dados["categorias"][tipo] = list(dict.fromkeys(nomes))  # sem repetidos
    elif categorias is not None:
        ignorados += 1

    icones = conteudo.get("icones", {})
    if isinstance(icones, dict):
        dados["icones"] = {c: i for c, i in icones.items() if _texto_valido(i) and len(i) <= 8}
    else:
        ignorados += 1

    # Toda categoria usada num lançamento precisa estar na lista, para aparecer nas telas
    for item in dados["lancamentos"] + dados["recorrentes"]:
        lista = dados["categorias"][item["tipo"]]
        if item["categoria"] not in lista:
            lista.append(item["categoria"])

    return dados, ignorados


def _ligar_recorrentes(dados):
    """Arquivos antigos não tinham id nos recorrentes, e os lançamentos criados
    por eles só tinham "recorrente": true. Aqui cada um ganha seu id e os
    lançamentos são ligados ao recorrente com a mesma descrição e categoria."""
    for r in dados["recorrentes"]:
        if not isinstance(r.get("id"), str):
            r["id"] = uuid.uuid4().hex
    for l in dados["lancamentos"]:
        if l.get("recorrente") is True:
            for r in dados["recorrentes"]:
                if (r["tipo"], r["descricao"], r["categoria"]) == (l["tipo"], l["descricao"], l["categoria"]):
                    l["recorrente"] = r["id"]
                    break


def carregar_dados(arquivo=None):
    """Lê os dados do arquivo JSON.

    - Arquivo não existe: começa vazio.
    - Formato antigo (só uma lista de gastos): converte para o formato novo.
    - Arquivo ilegível: guarda uma cópia de backup e lança DadosCorrompidos.
      Assim o próximo salvamento não apaga o histórico antigo.
    - Alguns itens inválidos (valor que não é número, data errada...): copia o
      arquivo para um backup e lança DadosCorrompidos com o que deu para
      aproveitar em 'dados'.
    """
    arquivo = Path(arquivo or ARQUIVO)
    if not arquivo.exists():
        _lembrar_versao(arquivo)
        return dados_vazios()
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            conteudo = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        _guardar_backup(arquivo)

    if isinstance(conteudo, list):  # versão antiga do programa: só a lista de gastos
        conteudo = {"lancamentos": conteudo}
    if not isinstance(conteudo, dict):
        _guardar_backup(arquivo)

    dados, ignorados = _ler_conteudo(conteudo)
    _ligar_recorrentes(dados)
    _lembrar_versao(arquivo)
    if ignorados:
        backup = _nome_backup(arquivo)
        shutil.copy2(arquivo, backup)
        raise DadosCorrompidos(backup, dados, ignorados)
    return dados


def _backup_do_dia(arquivo, hoje=None):
    """Antes de gravar por cima, guarda uma cópia do arquivo por dia em
    "backups/" (a primeira versão de cada dia), mantendo os últimos 30 dias.
    Se a cópia não der certo, o salvamento continua normalmente."""
    if not arquivo.exists():
        return
    pasta = arquivo.parent / "backups"
    destino = pasta / f"{arquivo.stem}-{(hoje or date.today()).isoformat()}{arquivo.suffix}"
    try:
        if destino.exists():
            return
        pasta.mkdir(exist_ok=True)
        shutil.copy2(arquivo, destino)
        copias = sorted(pasta.glob(f"{arquivo.stem}-????-??-??{arquivo.suffix}"))
        for antiga in copias[:-DIAS_DE_BACKUP]:
            antiga.unlink()
    except OSError:
        pass


def salvar_dados(dados, arquivo=None, forcar=False):
    """Grava os dados no arquivo JSON de forma segura.

    Escreve primeiro num arquivo temporário e só depois troca pelo original.
    Se o computador desligar no meio, o arquivo antigo continua inteiro.

    Se o arquivo foi alterado por outro programa depois de carregado, lança
    DadosAlteradosPorFora em vez de apagar essas mudanças (forcar=True grava
    mesmo assim).
    """
    arquivo = Path(arquivo or ARQUIVO)
    chave = str(arquivo.resolve())
    if not forcar and chave in _versoes and _versao(arquivo) != _versoes[chave]:
        raise DadosAlteradosPorFora()

    _backup_do_dia(arquivo)
    temporario = arquivo.with_name(arquivo.name + ".tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporario, arquivo)  # troca "atômica": ou fica o antigo, ou o novo
    _lembrar_versao(arquivo)


# ----------------------------------------------------------------------
# Validação do que o usuário digita
# ----------------------------------------------------------------------

# Jeito brasileiro: 1.234,56  ·  1234,56  ·  1.500 (mil e quinhentos)  ·  25
_FORMATO_BRASILEIRO = re.compile(r"\d{1,3}(\.\d{3})+(,\d+)?|\d+(,\d+)?")
# Ponto como separador decimal: 1234.56  ·  0.5
_FORMATO_PONTO = re.compile(r"\d+\.\d+")


def validar_valor(texto, aceitar_zero=False):
    """Converte o valor digitado em reais: '25,90' -> 25.9.

    Aceita o jeito brasileiro (1.234,56 e 1.500 = mil e quinhentos) e também
    ponto decimal (1234.56). Arredonda para centavos. Lança ValueError com a
    mensagem do erro. Com aceitar_zero=True, '0' é aceito (retorna 0.0).
    """
    texto = texto.replace("R$", "").replace(" ", "").strip()
    if texto.startswith("-"):
        raise ValueError("O valor precisa ser maior que zero.")
    if _FORMATO_BRASILEIRO.fullmatch(texto):
        texto = texto.replace(".", "").replace(",", ".")
    elif not _FORMATO_PONTO.fullmatch(texto):
        raise ValueError("Digite um número válido, por exemplo: 25,90 ou 1.234,56")

    valor = Decimal(texto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if valor == 0 and aceitar_zero:
        return 0.0
    if valor <= 0:
        raise ValueError("O valor precisa ser maior que zero.")
    if valor > VALOR_MAXIMO:
        raise ValueError(f"Valor alto demais. O máximo é {formatar_reais(VALOR_MAXIMO)}.")
    return float(valor)


def validar_data(texto):
    """Converte DD/MM/AAAA em '2026-10-15'. Texto vazio = hoje."""
    texto = texto.strip()
    if texto == "":
        return date.today().isoformat()
    try:
        return datetime.strptime(texto, "%d/%m/%Y").date().isoformat()
    except ValueError:
        raise ValueError("Data inválida. Use o formato DD/MM/AAAA (ex: 15/10/2026).")


def validar_mes(texto):
    """Converte MM/AAAA em '2026-10'."""
    try:
        return datetime.strptime(texto.strip(), "%m/%Y").strftime("%Y-%m")
    except ValueError:
        raise ValueError("Mês inválido. Use o formato MM/AAAA (ex: 10/2026).")


# ----------------------------------------------------------------------
# Formatação para mostrar na tela
# ----------------------------------------------------------------------

def formatar_reais(valor):
    """Formata 1234.5 como 'R$ 1.234,50' (padrão brasileiro)."""
    texto = f"{valor:,.2f}"  # 1,234.50
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def formatar_saldo(valor):
    """Como formatar_reais, mas com sinal quando negativo: '- R$ 50,00'."""
    return f"- {formatar_reais(-valor)}" if valor < 0 else formatar_reais(valor)


def formatar_numero(valor):
    """1234.5 -> '1.234,50' (para preencher campos de edição)."""
    return formatar_reais(valor)[3:]


def formatar_data(iso):
    """Converte '2026-10-15' em '15/10/2026'."""
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y")


def formatar_mes(mes):
    """'2026-10' -> 'Outubro de 2026'."""
    ano, numero = mes.split("-")
    return f"{NOMES_MESES[int(numero) - 1]} de {ano}"


def formatar_mes_curto(mes):
    """'2026-10' -> 'out/26'."""
    ano, numero = mes.split("-")
    return f"{NOMES_MESES[int(numero) - 1][:3].lower()}/{ano[2:]}"


# ----------------------------------------------------------------------
# Meses
# ----------------------------------------------------------------------

def mes_atual(hoje=None):
    return (hoje or date.today()).isoformat()[:7]


def somar_meses(mes, quantidade):
    """somar_meses('2026-12', 1) -> '2027-01'. Aceita quantidade negativa."""
    ano, numero = map(int, mes.split("-"))
    total = ano * 12 + (numero - 1) + quantidade
    return f"{total // 12}-{total % 12 + 1:02d}"


def data_no_mes(mes, dia):
    """Dia 'dia' do mês. Se o mês for mais curto (31 em fevereiro), usa o último dia."""
    ano, numero = map(int, mes.split("-"))
    ultimo_dia = calendar.monthrange(ano, numero)[1]
    return date(ano, numero, min(dia, ultimo_dia))


# ----------------------------------------------------------------------
# Cálculos (sempre somando em centavos)
# ----------------------------------------------------------------------

def _centavos(valor):
    return round(valor * 100)


def valor_com_sinal(lancamento):
    """Receita conta positivo, despesa conta negativo."""
    return lancamento["valor"] if lancamento["tipo"] == "receita" else -lancamento["valor"]


def eh_futuro(lancamento, hoje=None):
    """Lançamento com data depois de hoje (uma conta agendada, por exemplo)."""
    return lancamento["data"] > (hoje or date.today()).isoformat()


def esta_pendente(lancamento):
    """Conta a pagar que ainda não foi paga."""
    return lancamento.get("pendente") is True


def esta_atrasado(lancamento, hoje=None):
    return esta_pendente(lancamento) and lancamento["data"] < (hoje or date.today()).isoformat()


def calcular_saldo(lancamentos, ate=None):
    """Receitas menos despesas.

    Com 'ate' (uma data), é o saldo daquele dia: ignora o que vem depois dela
    e as contas a pagar que ainda não foram pagas.
    """
    if ate:
        lancamentos = [l for l in lancamentos if not eh_futuro(l, ate) and not esta_pendente(l)]
    return sum(_centavos(valor_com_sinal(l)) for l in lancamentos) / 100


def _normalizar(texto):
    """Minúsculas e sem acentos, para a busca achar 'salario' em 'Salário'."""
    sem_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem_acentos if not unicodedata.combining(c)).lower()


def filtrar(lancamentos, mes=None, busca=""):
    """Lançamentos de um mês (None = todos) que contêm o texto buscado.

    Retorna pares (posição na lista original, lançamento), do mais recente
    para o mais antigo. A posição serve para editar ou remover depois.
    """
    busca = _normalizar(busca.strip())
    resultado = []
    for indice, lancamento in enumerate(lancamentos):
        if mes and lancamento["data"][:7] != mes:
            continue
        texto = _normalizar(f"{lancamento['descricao']} {lancamento['categoria']}")
        if busca and busca not in texto:
            continue
        resultado.append((indice, lancamento))
    resultado.sort(key=lambda par: par[1]["data"], reverse=True)
    return resultado


def totais_por_tipo(lancamentos):
    """{'receita': total, 'despesa': total}"""
    centavos = {tipo: 0 for tipo in TIPOS}
    for l in lancamentos:
        centavos[l["tipo"]] += _centavos(l["valor"])
    return {tipo: valor / 100 for tipo, valor in centavos.items()}


def totais_por_mes(lancamentos):
    """{'2026-10': {'receita': total, 'despesa': total}, ...}"""
    por_mes = {}
    for l in lancamentos:
        por_mes.setdefault(l["data"][:7], []).append(l)
    return {mes: totais_por_tipo(lista) for mes, lista in por_mes.items()}


def totais_por_categoria(lancamentos, tipo="despesa"):
    """{'Alimentação': total, ...} considerando só lançamentos do tipo pedido."""
    centavos = {}
    for l in lancamentos:
        if l["tipo"] == tipo:
            centavos[l["categoria"]] = centavos.get(l["categoria"], 0) + _centavos(l["valor"])
    return {categoria: valor / 100 for categoria, valor in centavos.items()}


def situacao_orcamento(gasto, limite):
    """'sem' (não tem limite), 'ok', 'alerta' (usou 80% ou mais) ou 'estourado'."""
    if not limite:
        return "sem"
    if gasto > limite:
        return "estourado"
    if gasto >= limite * ALERTA_ORCAMENTO:
        return "alerta"
    return "ok"


# ----------------------------------------------------------------------
# Categorias
# ----------------------------------------------------------------------

def adicionar_categoria(dados, tipo, nome):
    """Cria uma categoria nova. Lança ValueError se o nome for inválido ou repetido."""
    nome = " ".join(nome.split())
    if not nome:
        raise ValueError("Digite o nome da categoria.")
    if len(nome) > TAMANHO_MAXIMO_CATEGORIA:
        raise ValueError(f"Nome muito longo (máximo de {TAMANHO_MAXIMO_CATEGORIA} letras).")
    lista = categorias_do_tipo(dados, tipo)
    for existente in lista:
        if _normalizar(existente) == _normalizar(nome):
            raise ValueError(f"A categoria \"{existente}\" já existe.")
    lista.append(nome)
    return nome


def remover_categoria(dados, tipo, nome):
    """Apaga uma categoria que não está em uso. Lança ValueError se não puder."""
    lista = categorias_do_tipo(dados, tipo)
    usos = sum(1 for item in dados["lancamentos"] + dados["recorrentes"]
               if item["tipo"] == tipo and item["categoria"] == nome)
    if usos:
        raise ValueError(f"\"{nome}\" é usada em {usos} lançamento(s) e por isso não pode ser removida.")
    if len(lista) <= 1:
        raise ValueError("É preciso ter pelo menos uma categoria.")
    lista.remove(nome)
    if tipo == "despesa":
        dados["orcamentos"].pop(nome, None)
    if nome not in categorias_do_tipo(dados, "receita" if tipo == "despesa" else "despesa"):
        dados["icones"].pop(nome, None)


def icone_da_categoria(dados, categoria):
    return dados["icones"].get(categoria) or ICONES_PADRAO.get(categoria, ICONE_GENERICO)


def definir_icone(dados, categoria, icone):
    if icone not in ICONES_PARA_ESCOLHER and icone not in ICONES_PADRAO.values():
        raise ValueError("Escolha um dos ícones da lista.")
    dados["icones"][categoria] = icone


# ----------------------------------------------------------------------
# Lançamentos recorrentes (salário, aluguel...)
# ----------------------------------------------------------------------

def criar_recorrente(dados, lancamento):
    """Faz um lançamento (que já foi adicionado) se repetir todo mês, no mesmo dia."""
    recorrente = {
        "id": uuid.uuid4().hex,
        "tipo": lancamento["tipo"],
        "descricao": lancamento["descricao"],
        "valor": lancamento["valor"],
        "categoria": lancamento["categoria"],
        "dia": int(lancamento["data"][8:]),
        "ultimo_mes": lancamento["data"][:7],  # este mês já foi lançado
    }
    # Uma conta a pagar que se repete (aluguel, luz...) volta todo mês como conta a pagar
    if esta_pendente(lancamento):
        recorrente["pendente"] = True
    if lancamento.get("conta"):
        recorrente["conta"] = lancamento["conta"]
    dados["recorrentes"].append(recorrente)
    lancamento["recorrente"] = recorrente["id"]
    return recorrente


def recorrente_do_lancamento(dados, lancamento):
    """O recorrente que criou este lançamento, ou None se não houver (mais)."""
    identificador = lancamento.get("recorrente")
    for r in dados["recorrentes"]:
        if r["id"] == identificador:
            return r
    return None


def atualizar_recorrente(recorrente, lancamento):
    """Os próximos meses passam a usar os dados deste lançamento (valor, dia...)."""
    recorrente.update(tipo=lancamento["tipo"], descricao=lancamento["descricao"],
                      valor=lancamento["valor"], categoria=lancamento["categoria"],
                      dia=int(lancamento["data"][8:]))


def parar_recorrente(dados, recorrente):
    """Para de criar o lançamento todo mês. Os que já foram criados continuam."""
    dados["recorrentes"].remove(recorrente)


def gerar_recorrentes(dados, hoje=None):
    """Cria os lançamentos recorrentes cuja data já chegou e que ainda não foram criados.

    Se o programa ficou meses sem abrir, cria todos os meses que faltaram.
    Retorna quantos lançamentos foram criados.
    """
    hoje = hoje or date.today()
    criados = 0
    for r in dados["recorrentes"]:
        mes = somar_meses(r["ultimo_mes"], 1)
        while data_no_mes(mes, r["dia"]) <= hoje:
            lancamento = {
                "tipo": r["tipo"],
                "descricao": r["descricao"],
                "valor": r["valor"],
                "categoria": r["categoria"],
                "data": data_no_mes(mes, r["dia"]).isoformat(),
                "recorrente": r["id"],
            }
            if r.get("pendente"):
                lancamento["pendente"] = True
            if r.get("conta"):
                lancamento["conta"] = r["conta"]
            dados["lancamentos"].append(lancamento)
            r["ultimo_mes"] = mes
            mes = somar_meses(mes, 1)
            criados += 1
    return criados


# ----------------------------------------------------------------------
# Comparação com o mês anterior
# ----------------------------------------------------------------------

def variacao(atual, anterior):
    """Quanto 'atual' mudou em relação a 'anterior', em % (25.0 = subiu 25%).
    None quando não há com o que comparar (anterior igual a zero)."""
    if not anterior:
        return None
    return (atual - anterior) / anterior * 100


# ----------------------------------------------------------------------
# Compras parceladas
# ----------------------------------------------------------------------

def criar_parcelas(dados, lancamento, quantidade):
    """Divide uma compra (o 'lancamento', com o valor total) em parcelas mensais.

    A primeira parcela fica na data da compra e as outras no mesmo dia dos
    meses seguintes. Os centavos que sobram da divisão vão para as primeiras
    parcelas (R$ 100 em 3x = 33,34 + 33,33 + 33,33). Retorna as parcelas.
    """
    if not 2 <= quantidade <= MAXIMO_PARCELAS:
        raise ValueError(f"O número de parcelas precisa ser de 2 a {MAXIMO_PARCELAS}.")
    total = _centavos(lancamento["valor"])
    if total < quantidade:
        raise ValueError("O valor é pequeno demais para tantas parcelas.")
    base, resto = divmod(total, quantidade)
    compra = uuid.uuid4().hex
    mes, dia = lancamento["data"][:7], int(lancamento["data"][8:])
    parcelas = []
    for numero in range(1, quantidade + 1):
        parcela = dict(lancamento)
        parcela.update(
            valor=(base + (1 if numero <= resto else 0)) / 100,
            data=data_no_mes(somar_meses(mes, numero - 1), dia).isoformat(),
            descricao=f"{lancamento['descricao']} ({numero}/{quantidade})",
            compra=compra,
            parcela=f"{numero}/{quantidade}",
        )
        parcelas.append(parcela)
    dados["lancamentos"].extend(parcelas)
    return parcelas


def parcelas_seguintes(dados, lancamento):
    """Esta parcela e as que vêm depois dela, da mesma compra: [(posição, lançamento), ...]."""
    compra = lancamento.get("compra")
    if not compra:
        return []
    return [(i, l) for i, l in enumerate(dados["lancamentos"])
            if l.get("compra") == compra and l["data"] >= lancamento["data"]]


# ----------------------------------------------------------------------
# Contas a pagar
# ----------------------------------------------------------------------

def contas_a_pagar(lancamentos):
    """As contas ainda não pagas, da que vence primeiro para a última: [(posição, lançamento)]."""
    pendentes = [(i, l) for i, l in enumerate(lancamentos) if esta_pendente(l)]
    return sorted(pendentes, key=lambda par: par[1]["data"])


def marcar_pago(lancamento, hoje=None):
    """A conta foi paga hoje: sai das contas a pagar e passa a contar no saldo."""
    lancamento.pop("pendente", None)
    lancamento["data"] = (hoje or date.today()).isoformat()


# ----------------------------------------------------------------------
# Contas e cartões
# ----------------------------------------------------------------------

def _nome_sem_repetir(lista, nome, tamanho_maximo, o_que):
    nome = " ".join(nome.split())
    if not nome:
        raise ValueError(f"Digite o nome {o_que}.")
    if len(nome) > tamanho_maximo:
        raise ValueError(f"Nome muito longo (máximo de {tamanho_maximo} letras).")
    for item in lista:
        if _normalizar(item["nome"]) == _normalizar(nome):
            raise ValueError(f"Já existe \"{item['nome']}\".")
    return nome


def criar_conta(dados, nome, tipo, fechamento=None, vencimento=None, limite=None):
    """Cria uma conta (corrente, dinheiro) ou um cartão de crédito.

    Cartões precisam do dia em que a fatura fecha e do dia em que ela vence.
    """
    if tipo not in TIPOS_DE_CONTA:
        raise ValueError("Escolha o tipo da conta.")
    nome = _nome_sem_repetir(dados["contas"], nome, TAMANHO_MAXIMO_CATEGORIA, "da conta")
    conta = {"id": uuid.uuid4().hex, "nome": nome, "tipo": tipo}
    if tipo == "cartao":
        for dia in (fechamento, vencimento):
            if not _dia_valido(dia):
                raise ValueError("Os dias de fechamento e de vencimento precisam ser de 1 a 31.")
        conta.update(fechamento=fechamento, vencimento=vencimento)
        if limite:
            conta["limite"] = limite
    dados["contas"].append(conta)
    return conta


def conta_por_id(dados, identificador):
    for conta in dados["contas"]:
        if conta["id"] == identificador:
            return conta
    return None


def remover_conta(dados, conta):
    """Apaga a conta. Os lançamentos dela continuam, só deixam de estar ligados a ela."""
    dados["contas"].remove(conta)
    for item in dados["lancamentos"] + dados["recorrentes"]:
        if item.get("conta") == conta["id"]:
            del item["conta"]


def saldo_da_conta(lancamentos, conta, hoje=None):
    """Saldo de uma conta corrente ou de dinheiro (o que entrou menos o que saiu nela)."""
    da_conta = [l for l in lancamentos if l.get("conta") == conta["id"]]
    return calcular_saldo(da_conta, ate=hoje or date.today())


def mes_da_fatura(conta, data):
    """Em que fatura do cartão cai uma compra feita em 'data' ('2026-10-15').

    A resposta é o mês em que a fatura fecha: compras até o dia do fechamento
    entram na fatura deste mês; depois dele, na do mês seguinte.
    """
    mes = data[:7]
    if data <= data_no_mes(mes, conta["fechamento"]).isoformat():
        return mes
    return somar_meses(mes, 1)


def fatura(lancamentos, conta, mes):
    """A fatura do cartão que fecha em 'mes'.

    Retorna {"mes", "fechamento", "vencimento" (datas), "total", "itens": [(posição, lançamento)]}.
    Receitas no cartão (um estorno, por exemplo) diminuem o total.
    """
    itens = [(i, l) for i, l in enumerate(lancamentos)
             if l.get("conta") == conta["id"] and mes_da_fatura(conta, l["data"]) == mes]
    itens.sort(key=lambda par: par[1]["data"], reverse=True)
    mes_vencimento = mes if conta["vencimento"] > conta["fechamento"] else somar_meses(mes, 1)
    return {
        "mes": mes,
        "fechamento": data_no_mes(mes, conta["fechamento"]),
        "vencimento": data_no_mes(mes_vencimento, conta["vencimento"]),
        "total": -calcular_saldo([l for _, l in itens]),
        "itens": itens,
    }


def limite_disponivel(lancamentos, conta, hoje=None):
    """Quanto do limite do cartão ainda pode ser usado: o limite menos a fatura
    aberta e as parcelas que vão cair nas próximas faturas. None sem limite."""
    if not conta.get("limite"):
        return None
    aberta = mes_da_fatura(conta, (hoje or date.today()).isoformat())
    usado = [l for l in lancamentos
             if l.get("conta") == conta["id"] and mes_da_fatura(conta, l["data"]) >= aberta]
    return conta["limite"] + calcular_saldo(usado)


# ----------------------------------------------------------------------
# Metas de economia
# ----------------------------------------------------------------------

def criar_meta(dados, nome, alvo, prazo=None):
    """Uma meta como "Viagem: juntar R$ 5.000 até julho de 2027" ('prazo' é opcional)."""
    nome = _nome_sem_repetir(dados["metas"], nome, 40, "da meta")
    meta = {"id": uuid.uuid4().hex, "nome": nome, "alvo": alvo, "guardado": 0.0}
    if prazo:
        meta["prazo"] = prazo
    dados["metas"].append(meta)
    return meta


def meta_por_id(dados, identificador):
    for meta in dados["metas"]:
        if meta["id"] == identificador:
            return meta
    return None


def movimentar_meta(meta, valor):
    """Guarda (valor positivo) ou retira (negativo) dinheiro da meta."""
    guardado = _centavos(meta["guardado"]) + _centavos(valor)
    if guardado < 0:
        raise ValueError(f"Só há {formatar_reais(meta['guardado'])} guardados nesta meta.")
    meta["guardado"] = guardado / 100


def progresso_da_meta(meta, hoje=None):
    """{"porcentagem", "falta", "por_mes"}: 'por_mes' é quanto guardar por mês
    para chegar no prazo (None sem prazo, ou se o prazo já passou)."""
    falta = max(_centavos(meta["alvo"]) - _centavos(meta["guardado"]), 0) / 100
    por_mes = None
    if meta.get("prazo") and falta:
        meses = (int(meta["prazo"][:4]) * 12 + int(meta["prazo"][5:])) - \
                (int(mes_atual(hoje)[:4]) * 12 + int(mes_atual(hoje)[5:])) + 1
        if meses > 0:
            por_mes = math.ceil(falta * 100 / meses) / 100
    return {"porcentagem": min(meta["guardado"] / meta["alvo"] * 100, 100),
            "falta": falta, "por_mes": por_mes}


# ----------------------------------------------------------------------
# Cofrinho (dinheiro guardado, sem objetivo definido)
# ----------------------------------------------------------------------

def saldo_do_cofrinho(dados):
    """Quanto há no cofrinho: o que foi guardado menos o que foi retirado."""
    return sum(_centavos(m["valor"]) for m in dados["cofrinho"]) / 100


def total_guardado(dados):
    """O cofrinho mais o que está guardado nas metas."""
    return (_centavos(saldo_do_cofrinho(dados))
            + sum(_centavos(m["guardado"]) for m in dados["metas"])) / 100


def movimentar_cofrinho(dados, valor, descricao="", data=None):
    """Guarda (valor positivo) ou retira (negativo) dinheiro do cofrinho.
    Não deixa retirar mais do que há guardado. Retorna o movimento."""
    if valor < 0 and _centavos(-valor) > _centavos(saldo_do_cofrinho(dados)):
        raise ValueError(f"Só há {formatar_reais(saldo_do_cofrinho(dados))} no cofrinho.")
    movimento = {
        "id": uuid.uuid4().hex,
        "data": data or date.today().isoformat(),
        "valor": valor,
        "descricao": " ".join(descricao.split())[:60] or ("Guardado" if valor > 0 else "Retirado"),
    }
    dados["cofrinho"].append(movimento)
    return movimento


def desfazer_movimento(dados, identificador):
    """Apaga um movimento do cofrinho (um lançado errado, por exemplo).
    Não deixa o cofrinho ficar negativo. Retorna o movimento apagado."""
    for movimento in dados["cofrinho"]:
        if movimento["id"] == identificador:
            if _centavos(saldo_do_cofrinho(dados)) - _centavos(movimento["valor"]) < 0:
                raise ValueError("Apagar este movimento deixaria o cofrinho negativo.")
            dados["cofrinho"].remove(movimento)
            return movimento
    raise ValueError("Esse movimento não existe mais.")


def movimentos_do_cofrinho(dados):
    """Do mais recente para o mais antigo (no mesmo dia, o último lançado vem primeiro)."""
    pares = sorted(enumerate(dados["cofrinho"]), key=lambda par: (par[1]["data"], par[0]), reverse=True)
    return [m for _, m in pares]


# ----------------------------------------------------------------------
# Importar o extrato do banco (OFX ou CSV)
# ----------------------------------------------------------------------

MAXIMO_IMPORTACAO = 500


def _numero_do_extrato(texto):
    """'-1.234,56', '-1234.56', 'R$ 50,00' -> número com sinal (ou None)."""
    texto = texto.replace("R$", "").replace(" ", "").replace("\xa0", "").strip()
    negativo = texto.startswith("-") or (texto.startswith("(") and texto.endswith(")"))
    texto = texto.strip("-+()")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(texto)
    except ArithmeticError:
        return None
    if not valor.is_finite():
        return None
    return float(-valor if negativo else valor)


def _data_do_extrato(texto):
    texto = texto.strip()
    if re.fullmatch(r"\d{8}.*", texto):  # OFX: 20261015120000[-3:BRT]
        texto = f"{texto[:4]}-{texto[4:6]}-{texto[6:8]}"
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            continue
    return None


def _ler_ofx(texto):
    linhas = []
    for bloco in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", texto, re.S | re.I):
        campos = {nome.upper(): valor.strip()
                  for nome, valor in re.findall(r"<(\w+)>([^<\r\n]*)", bloco)}
        descricao = campos.get("MEMO") or campos.get("NAME") or ""
        linhas.append((campos.get("DTPOSTED", ""), descricao, campos.get("TRNAMT", "")))
    return linhas


def _coluna(cabecalho, *nomes):
    for posicao, titulo in enumerate(cabecalho):
        titulo = _normalizar(titulo.strip())
        if any(titulo.startswith(nome) for nome in nomes):
            return posicao
    return None


def _ler_csv(texto):
    linhas = [l for l in texto.splitlines() if l.strip()]
    if not linhas:
        return []
    separador = ";" if linhas[0].count(";") >= linhas[0].count(",") else ","
    tabela = list(csv.reader(linhas, delimiter=separador))
    cabecalho = tabela[0]
    data = _coluna(cabecalho, "data", "date")
    descricao = _coluna(cabecalho, "descri", "historico", "title", "memo", "lancamento",
                        "estabelecimento", "detalhe")
    valor = _coluna(cabecalho, "valor", "amount", "quantia")
    if None in (data, valor):
        raise ValueError("Não encontrei as colunas de data e de valor no arquivo. "
                         "A primeira linha precisa ter os títulos, como: Data;Descrição;Valor")
    resultado = []
    for linha in tabela[1:]:
        if len(linha) <= max(data, valor):
            continue
        texto_descricao = linha[descricao] if descricao is not None and descricao < len(linha) else ""
        resultado.append((linha[data], texto_descricao, linha[valor]))
    return resultado


def ler_extrato(conteudo, nome_do_arquivo="", inverter=False):
    """Lê o extrato baixado do banco (OFX ou CSV) e retorna os lançamentos:
    [{"tipo", "descricao", "valor", "data"}, ...], sem categoria.

    Valor negativo vira despesa e positivo vira receita. Na fatura do cartão
    geralmente é o contrário (o gasto vem positivo): para isso, inverter=True.
    Lança ValueError se o arquivo não puder ser lido.
    """
    for codificacao in ("utf-8-sig", "cp1252", "latin-1"):  # latin-1 lê qualquer coisa
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    if "<OFX>" in texto.upper() or nome_do_arquivo.lower().endswith(".ofx"):
        linhas = _ler_ofx(texto)
    else:
        linhas = _ler_csv(texto)

    lancamentos = []
    for data, descricao, valor in linhas:
        data, numero = _data_do_extrato(data), _numero_do_extrato(valor)
        if not data or not numero or abs(numero) > VALOR_MAXIMO:
            continue
        if inverter:
            numero = -numero
        lancamentos.append({
            "tipo": "despesa" if numero < 0 else "receita",
            "descricao": " ".join(descricao.split())[:80] or "Sem descrição",
            "valor": float(Decimal(str(abs(numero))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "data": data,
        })
    if not lancamentos:
        raise ValueError("Nenhum lançamento encontrado no arquivo. Ele é um extrato em OFX ou CSV?")
    return lancamentos[:MAXIMO_IMPORTACAO]


def parece_ja_lancado(dados, item):
    """Já existe um lançamento com a mesma data, tipo e valor (provavelmente o mesmo)."""
    return any((l["data"], l["tipo"], _centavos(l["valor"])) ==
               (item["data"], item["tipo"], _centavos(item["valor"])) for l in dados["lancamentos"])


def sugerir_categoria(dados, descricao, tipo):
    """A categoria usada da última vez num lançamento com a mesma descrição, ou "Outros"."""
    procurada = _normalizar(descricao.strip())
    for l in reversed(dados["lancamentos"]):
        if l["tipo"] == tipo and _normalizar(re.sub(r" \(\d+/\d+\)$", "", l["descricao"])) == procurada:
            return l["categoria"]
    lista = categorias_do_tipo(dados, tipo)
    return "Outros" if "Outros" in lista else lista[-1]


# ----------------------------------------------------------------------
# Exportação
# ----------------------------------------------------------------------

def exportar_csv(lancamentos, caminho):
    """Gera uma planilha CSV que abre direto no Excel em português
    (separador ';', vírgula decimal e acentos corretos)."""
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["Data", "Tipo", "Descrição", "Categoria", "Valor"])
        for l in sorted(lancamentos, key=lambda l: l["data"]):
            escritor.writerow([
                formatar_data(l["data"]),
                l["tipo"].capitalize(),
                l["descricao"],
                l["categoria"],
                f"{valor_com_sinal(l):.2f}".replace(".", ","),
            ])
