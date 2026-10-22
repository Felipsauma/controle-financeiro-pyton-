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
    "categorias":  {"despesa": ["Alimentação", ...], "receita": ["Salário", ...]}
  }

Os lançamentos criados por um recorrente guardam o id dele em "recorrente".

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


def categorias_do_tipo(dados, tipo):
    return dados["categorias"]["receita" if tipo == "receita" else "despesa"]


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
            "categorias": {tipo: list(CATEGORIAS_PADRAO[tipo]) for tipo in TIPOS}}


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


def _ler_conteudo(conteudo):
    """Monta os dados a partir do JSON lido, deixando de fora o que for inválido.

    Retorna (dados, quantos itens foram ignorados).
    """
    dados = dados_vazios()
    ignorados = 0

    for chave, valido in [("lancamentos", _lancamento_valido), ("recorrentes", _recorrente_valido)]:
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


def calcular_saldo(lancamentos, ate=None):
    """Receitas menos despesas. Com 'ate' (uma data), ignora o que vem depois dela."""
    if ate:
        lancamentos = [l for l in lancamentos if not eh_futuro(l, ate)]
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
            dados["lancamentos"].append({
                "tipo": r["tipo"],
                "descricao": r["descricao"],
                "valor": r["valor"],
                "categoria": r["categoria"],
                "data": data_no_mes(mes, r["dia"]).isoformat(),
                "recorrente": r["id"],
            })
            r["ultimo_mes"] = mes
            mes = somar_meses(mes, 1)
            criados += 1
    return criados


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
