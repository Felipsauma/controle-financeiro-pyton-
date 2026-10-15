"""
Núcleo do Controle de Gastos
----------------------------
Tudo o que não é tela fica aqui: salvar e carregar os dados, validar o que
o usuário digita, calcular saldos e totais, orçamentos, lançamentos
recorrentes e exportação para CSV.

Quem usa este módulo:
  - controle_gastos.py  (versão de terminal)
  - app_gastos.py       (versão com janela)
  - test_financas.py    (testes automáticos)

Formato do arquivo gastos.json:
  {
    "lancamentos": [{"tipo": "despesa", "descricao": "Almoço", "valor": 25.9,
                     "categoria": "Alimentação", "data": "2026-10-15"}, ...],
    "orcamentos":  {"Lazer": 300.0, ...},          # limite mensal por categoria
    "recorrentes": [{"tipo": "receita", "descricao": "Salário", "valor": 3500.0,
                     "categoria": "Salário", "dia": 5, "ultimo_mes": "2026-10"}, ...]
  }
"""

import calendar
import csv
import json
import os
import unicodedata
from datetime import date, datetime
from pathlib import Path

# Arquivo onde os dados são guardados (fica ao lado deste script)
ARQUIVO = Path(__file__).parent / "gastos.json"

TIPOS = ("despesa", "receita")
CATEGORIAS_DESPESA = ["Alimentação", "Transporte", "Moradia", "Lazer", "Saúde", "Educação", "Outros"]
CATEGORIAS_RECEITA = ["Salário", "Freelance", "Investimentos", "Presente", "Outros"]

NOMES_MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
               "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

# A partir de quanto do orçamento usado a categoria entra em "alerta" (80%)
ALERTA_ORCAMENTO = 0.8


def categorias_do_tipo(tipo):
    return CATEGORIAS_RECEITA if tipo == "receita" else CATEGORIAS_DESPESA


# ----------------------------------------------------------------------
# Salvar e carregar dados
# ----------------------------------------------------------------------

class DadosCorrompidos(Exception):
    """O arquivo de dados não pôde ser lido. Uma cópia dele foi guardada em 'backup'."""

    def __init__(self, backup):
        super().__init__(f"Arquivo de dados corrompido. Uma cópia foi guardada em {backup.name}")
        self.backup = backup


def dados_vazios():
    return {"lancamentos": [], "orcamentos": {}, "recorrentes": []}


def _guardar_backup(arquivo):
    """Renomeia o arquivo estragado para que ele nunca seja sobrescrito."""
    backup = arquivo.with_name(f"{arquivo.stem}-corrompido-{datetime.now():%Y%m%d-%H%M%S}{arquivo.suffix}")
    arquivo.replace(backup)
    raise DadosCorrompidos(backup)


def carregar_dados(arquivo=None):
    """Lê os dados do arquivo JSON.

    - Arquivo não existe: começa vazio.
    - Formato antigo (só uma lista de gastos): converte para o formato novo.
    - Arquivo corrompido: guarda uma cópia de backup e lança DadosCorrompidos.
      Assim o próximo salvamento não apaga o histórico antigo.
    """
    arquivo = Path(arquivo or ARQUIVO)
    if not arquivo.exists():
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

    dados = dados_vazios()
    dados.update(conteudo)
    for lancamento in dados["lancamentos"]:
        lancamento.setdefault("tipo", "despesa")  # antes só existiam despesas
    return dados


def salvar_dados(dados, arquivo=None):
    """Grava os dados no arquivo JSON de forma segura.

    Escreve primeiro num arquivo temporário e só depois troca pelo original.
    Se o computador desligar no meio, o arquivo antigo continua inteiro.
    """
    arquivo = Path(arquivo or ARQUIVO)
    temporario = arquivo.with_name(arquivo.name + ".tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporario, arquivo)  # troca "atômica": ou fica o antigo, ou o novo


# ----------------------------------------------------------------------
# Validação do que o usuário digita
# ----------------------------------------------------------------------

def validar_valor(texto):
    """Converte '25,90' em 25.9. Lança ValueError com a mensagem do erro."""
    texto = texto.strip().replace("R$", "").strip().replace(",", ".")
    try:
        valor = float(texto)
    except ValueError:
        raise ValueError("Digite um número válido, por exemplo: 25,90")
    if valor <= 0:
        raise ValueError("O valor precisa ser maior que zero.")
    return round(valor, 2)


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
    """25.9 -> '25,90' (para preencher campos de edição)."""
    return f"{valor:.2f}".replace(".", ",")


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
# Cálculos
# ----------------------------------------------------------------------

def valor_com_sinal(lancamento):
    """Receita conta positivo, despesa conta negativo."""
    return lancamento["valor"] if lancamento["tipo"] == "receita" else -lancamento["valor"]


def calcular_saldo(lancamentos):
    return round(sum(valor_com_sinal(l) for l in lancamentos), 2)


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
    totais = {tipo: 0 for tipo in TIPOS}
    for l in lancamentos:
        totais[l["tipo"]] += l["valor"]
    return {tipo: round(valor, 2) for tipo, valor in totais.items()}


def totais_por_mes(lancamentos):
    """{'2026-10': {'receita': total, 'despesa': total}, ...}"""
    por_mes = {}
    for l in lancamentos:
        por_mes.setdefault(l["data"][:7], []).append(l)
    return {mes: totais_por_tipo(lista) for mes, lista in por_mes.items()}


def totais_por_categoria(lancamentos, tipo="despesa"):
    """{'Alimentação': total, ...} considerando só lançamentos do tipo pedido."""
    totais = {}
    for l in lancamentos:
        if l["tipo"] == tipo:
            totais[l["categoria"]] = round(totais.get(l["categoria"], 0) + l["valor"], 2)
    return totais


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
# Lançamentos recorrentes (salário, aluguel...)
# ----------------------------------------------------------------------

def criar_recorrente(dados, lancamento):
    """Faz um lançamento (que já foi adicionado) se repetir todo mês, no mesmo dia."""
    dados["recorrentes"].append({
        "tipo": lancamento["tipo"],
        "descricao": lancamento["descricao"],
        "valor": lancamento["valor"],
        "categoria": lancamento["categoria"],
        "dia": int(lancamento["data"][8:]),
        "ultimo_mes": lancamento["data"][:7],  # este mês já foi lançado
    })
    lancamento["recorrente"] = True


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
                "recorrente": True,
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
