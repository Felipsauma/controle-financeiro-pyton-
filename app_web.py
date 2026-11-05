"""
Controle de Gastos Pessoais - versão para o navegador (Flask)
-------------------------------------------------------------
As mesmas funções das outras versões, numa página feita para o celular:
saldo, lançamentos (com busca, edição e remoção), orçamentos, gráficos,
lançamentos recorrentes, categorias e exportação para o Excel. Só nesta
versão: compras parceladas, contas a pagar, contas e cartões de crédito,
metas de economia e importação do extrato do banco.

O programa roda no computador e o celular abre a página pelo Wi-Fi. Como
qualquer aparelho da rede consegue abrir o endereço, a página pede senha.

As regras (salvar, calcular, validar...) ficam em financas.py e são as
mesmas das outras versões. Os dados ficam em "gastos.json".

Como rodar:
    pip install flask
    python app_web.py
(no Windows, também dá para só dar dois cliques em iniciar.bat)

Depois abra no celular o endereço que aparece no terminal (o celular
precisa estar no mesmo Wi-Fi). No iPhone, em Compartilhar > "Adicionar à
Tela de Início", a página ganha um ícone e abre como um app.

Na primeira vez o programa pede para criar uma senha. Ela fica guardada
(só um resumo dela, nunca a senha em si) em "config-web.json", então não é
pedida de novo. Para trocar: python app_web.py --nova-senha
A senha também pode vir da variável de ambiente CONTROLE_SENHA.
"""

import hashlib
import json
import math
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import zlib
from contextlib import contextmanager
from datetime import date, timedelta
from getpass import getpass
from hmac import compare_digest
from pathlib import Path

from flask import Flask, Response, abort, flash, redirect, render_template, request, session, url_for

from financas import (
    CAMPOS_DE_LIGACAO,
    ICONES_PARA_ESCOLHER,
    MAXIMO_PARCELAS,
    TIPOS,
    TIPOS_DE_CONTA,
    DadosAlteradosPorFora,
    DadosCorrompidos,
    adicionar_categoria,
    atualizar_recorrente,
    calcular_saldo,
    carregar_dados,
    categorias_do_tipo,
    conta_por_id,
    contas_a_pagar,
    criar_conta,
    criar_meta,
    criar_parcelas,
    criar_recorrente,
    data_no_mes,
    definir_icone,
    desfazer_movimento,
    eh_futuro,
    esta_atrasado,
    esta_pendente,
    exportar_csv,
    fatura,
    filtrar,
    formatar_data,
    formatar_mes,
    formatar_mes_curto,
    formatar_numero,
    formatar_reais,
    gerar_recorrentes,
    icone_da_categoria,
    ler_extrato,
    limite_disponivel,
    manter_extras,
    marcar_pago,
    mes_atual,
    mes_da_fatura,
    meta_por_id,
    movimentar_cofrinho,
    movimentar_meta,
    movimentos_do_cofrinho,
    parar_recorrente,
    parcelas_seguintes,
    parece_ja_lancado,
    progresso_da_meta,
    recorrente_do_lancamento,
    remover_categoria,
    remover_conta,
    saldo_da_conta,
    saldo_do_cofrinho,
    salvar_dados,
    situacao_orcamento,
    somar_meses,
    sugerir_categoria,
    totais_por_categoria,
    totais_por_mes,
    totais_por_tipo,
    total_guardado,
    validar_data,
    validar_valor,
    variacao,
)

PORTA = 5000

# Senha (só o resumo) e chave das sessões, para não pedir a senha a cada vez
ARQUIVO_CONFIG = Path(__file__).parent / "config-web.json"

# Cores das categorias, tiradas das cédulas do Real (R$ 100, 50, 5, 2, 20, 200...).
# O vermelho (R$ 10) e o verde ficam de fora: são as cores de despesa e receita.
CORES_CATEGORIAS = ["#2b5f8a", "#b07a25", "#6e5491", "#4e7585", "#c99a2e", "#8a6f5a", "#6b7f3a"]

DIAS_DA_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# Contas a pagar que aparecem na página inicial: as atrasadas e as que vencem em até 7 dias
DIAS_PARA_AVISAR = 7

# O "desfazer" guarda o que foi removido no cookie, que tem pouco espaço
TAMANHO_MAXIMO_DESFAZER = 3000


def resumo_da_senha(senha, sal=None):
    """O "resumo" (hash) da senha, que é o que fica guardado no arquivo.

    Com o resumo dá para conferir uma senha digitada, mas não dá para
    descobrir a senha. O scrypt é lento de propósito, para atrapalhar quem
    pegar o arquivo e tentar adivinhar a senha testando milhões delas.
    """
    sal = sal or secrets.token_bytes(16)
    resumo = hashlib.scrypt(senha.encode(), salt=sal, n=2**14, r=8, p=1)
    return {"sal": sal.hex(), "resumo": resumo.hex()}


def senha_confere(digitada, guardada):
    calculada = resumo_da_senha(digitada, bytes.fromhex(guardada["sal"]))
    return compare_digest(calculada["resumo"], guardada["resumo"])


def carregar_config(arquivo=ARQUIVO_CONFIG):
    try:
        config = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def salvar_config(config, arquivo=ARQUIVO_CONFIG):
    Path(arquivo).write_text(json.dumps(config, indent=2), encoding="utf-8")


def cor_da_categoria(categoria, categorias):
    if categoria in categorias:
        return CORES_CATEGORIAS[categorias.index(categoria) % len(CORES_CATEGORIAS)]
    return CORES_CATEGORIAS[-1]


def formatar_saldo(valor):
    """Saldo com o sinal de menos tipográfico (fica mais bonito na tela)."""
    return f"− {formatar_reais(-valor)}" if valor < 0 else formatar_reais(valor)


def formatar_variacao(porcentagem):
    """25.4 -> '25%'. Sem casas decimais: é só para ter uma ideia."""
    return f"{abs(round(porcentagem))}%"


def rotulo_dia(iso):
    """'2026-10-15' -> 'Hoje', 'Ontem' ou 'qui, 15/10/2026' (títulos da lista)."""
    dia = date.fromisoformat(iso)
    diferenca = (date.today() - dia).days
    if diferenca == 0:
        return "Hoje"
    if diferenca == 1:
        return "Ontem"
    if diferenca == -1:
        return "Amanhã"
    return f"{DIAS_DA_SEMANA[dia.weekday()]}, {formatar_data(iso)}"


def quando_vence(iso):
    """Texto curto para contas a pagar: 'venceu há 3 dias', 'vence hoje', 'vence em 5 dias'."""
    dias = (date.fromisoformat(iso) - date.today()).days
    if dias < -1:
        return f"venceu há {-dias} dias"
    if dias == -1:
        return "venceu ontem"
    if dias == 0:
        return "vence hoje"
    if dias == 1:
        return "vence amanhã"
    if dias <= 31:
        return f"vence em {dias} dias"
    return f"vence em {formatar_data(iso)}"


def chave_do_lancamento(lancamento):
    """Uma "impressão digital" do lançamento.

    A página manda a posição do lançamento na lista junto com a impressão
    digital dele. Se a lista mudou nesse meio-tempo (a versão de janela
    removeu algo, por exemplo), ela não bate e nada é editado por engano.
    """
    texto = json.dumps(lancamento, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(texto.encode()).hexdigest()[:16]


_FORMATO_MES = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def ler_mes(texto):
    """Mês pedido na página: '2026-10' fica igual, 'todos' vira None e
    qualquer outra coisa vira o mês atual."""
    if texto == "todos":
        return None
    if texto and _FORMATO_MES.fullmatch(texto):
        return texto
    return mes_atual()


def ler_data(texto):
    """O campo de data do navegador manda '2026-10-15'. Também aceita 15/10/2026."""
    texto = texto.strip()
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError:
        return validar_data(texto)  # vazio = hoje


def ler_dia(texto, nome):
    try:
        dia = int(texto)
    except (TypeError, ValueError):
        raise ValueError(f"Digite o dia do {nome} (de 1 a 31).")
    if not 1 <= dia <= 31:
        raise ValueError(f"O dia do {nome} precisa ser de 1 a 31.")
    return dia


# ----------------------------------------------------------------------
# Dados para os gráficos da página inicial
# ----------------------------------------------------------------------

def barras_das_categorias(dados, lancamentos_do_mes, mes, lancamentos_do_anterior=None):
    """Despesas por categoria, comparadas com o orçamento e com o mês anterior
    quando há um mês escolhido."""
    totais = totais_por_categoria(lancamentos_do_mes, "despesa")
    anteriores = totais_por_categoria(lancamentos_do_anterior or [], "despesa")
    # Orçamentos são mensais: só fazem sentido quando um mês foi escolhido
    orcamentos = dados["orcamentos"] if mes else {}
    categorias = sorted(set(totais) | set(orcamentos), key=lambda cat: totais.get(cat, 0), reverse=True)

    lista_categorias = categorias_do_tipo(dados, "despesa")
    total_geral = sum(totais.values()) or 1
    maior = max(totais.values(), default=0) or 1

    barras = []
    for categoria in categorias:
        gasto = totais.get(categoria, 0)
        limite = orcamentos.get(categoria)
        situacao = situacao_orcamento(gasto, limite)
        aviso = None
        if situacao == "sem":
            # Sem orçamento: barra proporcional à maior categoria
            proporcao = gasto / maior
            texto = f"{gasto / total_geral * 100:.0f}% das despesas"
        else:
            # Com orçamento: barra mostra quanto do limite já foi usado
            proporcao = min(gasto / limite, 1)
            texto = f"{gasto / limite * 100:.0f}% de {formatar_reais(limite)}"
            if situacao == "alerta":
                aviso = "Quase no limite"
            elif situacao == "estourado":
                aviso = f"Passou {formatar_reais(gasto - limite)}"
        mudanca = variacao(gasto, anteriores.get(categoria, 0)) if lancamentos_do_anterior is not None else None
        barras.append({"nome": categoria, "situacao": situacao, "texto": texto, "aviso": aviso,
                       "gasto": gasto, "variacao": mudanca,
                       "icone": icone_da_categoria(dados, categoria),
                       "cor": cor_da_categoria(categoria, lista_categorias),
                       "largura": round(proporcao * 100, 1)})
    return barras


def rosca(barras):
    """Fatias do gráfico de rosca (em % da volta), a partir das barras das categorias.

    O círculo do SVG tem circunferência 100, então o tamanho de cada fatia em %
    é direto o comprimento do traço.
    """
    total = sum(b["gasto"] for b in barras)
    fatias, inicio = [], 0.0
    for b in barras:
        if not b["gasto"]:
            continue
        tamanho = b["gasto"] / total * 100
        # Um vãozinho entre as fatias, menos quando só há uma
        traco = max(tamanho - 0.8, 0.3) if tamanho < 100 else 100
        fatias.append({"cor": b["cor"], "nome": b["nome"], "traco": round(traco, 3),
                       "resto": round(100 - traco, 3), "deslocamento": round(25 - inicio, 3)})
        inicio += tamanho
    return fatias


def evolucao(lancamentos, fim):
    """Receitas e despesas dos 6 meses até 'fim', em % do maior valor (altura das barras)."""
    totais = totais_por_mes(lancamentos)
    meses = [somar_meses(fim, i - 5) for i in range(6)]
    maior = max([totais.get(m, {}).get(t, 0) for m in meses for t in TIPOS] + [1])
    colunas = []
    for mes in meses:
        valores = totais.get(mes, {"receita": 0, "despesa": 0})
        colunas.append({"mes": mes, "rotulo": formatar_mes_curto(mes), "destaque": mes == fim,
                        "valores": valores,
                        "alturas": {t: round(valores[t] / maior * 100, 1) for t in TIPOS}})
    return colunas


# ----------------------------------------------------------------------
# Desenhos: ícone da tela de início (PNG) e o fundo da cédula (SVG)
# ----------------------------------------------------------------------

def _png(largura, altura, pixel):
    """Monta um arquivo PNG. pixel(x, y) devolve a cor (r, g, b) de cada ponto."""
    linhas = b"".join(b"\x00" + bytes(c for x in range(largura) for c in pixel(x, y))
                      for y in range(altura))

    def bloco(tipo, conteudo):
        return (struct.pack(">I", len(conteudo)) + tipo + conteudo
                + struct.pack(">I", zlib.crc32(tipo + conteudo)))

    cabecalho = struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)  # 8 bits, RGB
    return (b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", cabecalho)
            + bloco(b"IDAT", zlib.compress(linhas, 9)) + bloco(b"IEND", b""))


def desenhar_icone(tamanho=180):
    """Fundo azul da nota de R$ 100 com três barras cor de papel subindo.
    O iPhone arredonda os cantos sozinho."""
    azul, papel = (43, 95, 138), (237, 240, 235)
    barras = [(0.22, 0.36, 0.56), (0.43, 0.57, 0.40), (0.64, 0.78, 0.24)]  # (esquerda, direita, topo)

    def pixel(x, y):
        fx, fy = x / tamanho, y / tamanho
        for esquerda, direita, topo in barras:
            if esquerda <= fx < direita and topo <= fy < 0.78:
                return papel
        return azul

    return _png(tamanho, tamanho, pixel)


def desenhar_guilhoche(largura=400, altura=220):
    """As linhas finas e entrelaçadas das cédulas (o "guilhoché"), em SVG.

    Uma faixa de ondas atravessando a nota e uma roseta no canto. A página usa
    o desenho como máscara, então a cor vem do CSS (azul ou vermelho).
    """
    caminhos = []
    for i in range(18):
        fase = i * math.pi / 18
        pontos = []
        for x in range(0, largura + 1, 8):
            t = x / largura * 2 * math.pi
            y = altura * 0.64 + altura * 0.2 * math.sin(2 * t + fase) * math.cos(t / 2 - fase)
            pontos.append(f"{x},{y:.1f}")
        caminhos.append("M" + " L".join(pontos))
    cx, cy, raio = largura * 0.84, altura * 0.3, altura * 0.3
    for i in range(14):
        fase = i * math.pi / 14
        pontos = []
        for grau in range(0, 360, 3):
            a = math.radians(grau)
            r = raio * (0.55 + 0.45 * math.sin(6 * a + fase) ** 2)
            pontos.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
        caminhos.append("M" + " L".join(pontos) + "Z")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}" '
            f'preserveAspectRatio="xMidYMid slice"><path d="{" ".join(caminhos)}" '
            f'fill="none" stroke="#000" stroke-width="0.6"/></svg>')


# ----------------------------------------------------------------------
# O site
# ----------------------------------------------------------------------

def criar_app(senha, arquivo=None, chave=None):
    """Cria o site. 'arquivo' é o JSON dos dados (os testes usam um temporário).

    'senha' pode ser o texto da senha ou o resumo guardado (resumo_da_senha).
    'chave' assina o cookie de quem entrou: se for a mesma da última vez, o
    celular continua conectado depois que o programa é fechado e aberto de novo.
    Sem chave, uma nova é sorteada e todo mundo precisa digitar a senha de novo.
    """
    if isinstance(senha, str):
        senha = resumo_da_senha(senha)
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=chave or secrets.token_bytes(32),
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,  # extratos do banco de até 2 MB
    )
    # O Flask atende vários pedidos ao mesmo tempo; a trava faz um ler-alterar-salvar por vez
    trava = threading.Lock()
    png_do_icone = desenhar_icone()
    svg_do_guilhoche = desenhar_guilhoche()

    # ---------------- Dados ----------------

    def salvar(dados):
        """Grava os dados. Se não der, avisa na página e retorna False."""
        try:
            salvar_dados(dados, arquivo)
            return True
        except DadosAlteradosPorFora:
            flash("Os dados foram alterados por outro programa neste mesmo instante "
                  "(a versão de janela ou de terminal está aberta?). Nada foi salvo: "
                  "confira a lista e tente de novo.", "erro")
        except OSError as erro:
            flash(f"Não foi possível salvar os dados: {erro}", "erro")
        return False

    @contextmanager
    def dados_do_arquivo():
        """Carrega os dados do arquivo e cria os lançamentos recorrentes que venceram.

        Os dados são lidos de novo a cada pedido, então o que a versão de janela
        ou de terminal salvou aparece aqui. A trava fica presa até o fim do bloco.
        """
        with trava:
            try:
                dados = carregar_dados(arquivo)
            except DadosCorrompidos as erro:
                dados = erro.dados
                if erro.ignorados:
                    flash(f"{erro.ignorados} item(ns) inválido(s) nos dados salvos foram ignorados. "
                          f"Nada foi apagado: o arquivo original foi copiado para "
                          f"\"{erro.backup.name}\".", "aviso")
                else:
                    flash("Não foi possível ler os dados salvos. Nada foi apagado: o arquivo antigo "
                          f"foi guardado como \"{erro.backup.name}\" e o programa começou com "
                          "uma lista vazia.", "aviso")
                salvar(dados)  # grava a versão aproveitada, para o aviso não se repetir a cada página

            criados = gerar_recorrentes(dados)
            if criados:
                flash(f"{criados} lançamento(s) que se repetem todo mês foram adicionados "
                      "automaticamente.", "info")
                salvar(dados)
            yield dados

    def ler_dados():
        """Só para mostrar: carrega e solta a trava logo."""
        with dados_do_arquivo() as dados:
            return dados

    def achar_lancamento(dados, indice):
        """O lançamento que a página pediu, ou None (com aviso) se a lista mudou."""
        lista = dados["lancamentos"]
        if 0 <= indice < len(lista) and chave_do_lancamento(lista[indice]) == request.values.get("c"):
            return lista[indice]
        flash("Esse lançamento mudou ou foi removido em outro lugar. Confira a lista e tente de novo.",
              "erro")
        return None

    def voltar_para(data=None):
        """Mês para onde voltar depois de salvar: o do lançamento salvo, para a
        pessoa ver onde ele foi parar (a não ser que estivesse vendo todos os meses)."""
        voltar = request.values.get("voltar")
        if voltar == "todos":
            return "todos"
        return data[:7] if data else ler_mes(voltar)

    def itens_da_lista(dados, pares):
        """Prepara os lançamentos para as listas das páginas (ícone, cor, conta...)."""
        categorias = {tipo: categorias_do_tipo(dados, tipo) for tipo in TIPOS}
        contas = {c["id"]: c["nome"] for c in dados["contas"]}
        return [{"indice": i, "chave": chave_do_lancamento(l), "l": l,
                 "futuro": eh_futuro(l), "pendente": esta_pendente(l), "atrasado": esta_atrasado(l),
                 "icone": icone_da_categoria(dados, l["categoria"]),
                 "cor": cor_da_categoria(l["categoria"], categorias[l["tipo"]]),
                 "conta": contas.get(l.get("conta"))}
                for i, l in pares]

    # ---------------- Senha ----------------

    @app.before_request
    def pedir_senha():
        livres = ("entrar", "icone", "manifesto", "guilhoche", "static")
        if request.endpoint in livres or session.get("entrou"):
            return None
        return redirect(url_for("entrar"))

    @app.route("/entrar", methods=["GET", "POST"])
    def entrar():
        erro = None
        if request.method == "POST":
            if senha_confere(request.form.get("senha", ""), senha):
                session.clear()
                session.permanent = True  # continua logado por 90 dias
                session["entrou"] = True
                return redirect(url_for("inicio"))
            time.sleep(1)  # atrasa quem tenta adivinhar a senha
            erro = "Senha incorreta."
        return render_template("entrar.html", erro=erro)

    @app.post("/sair")
    def sair():
        session.clear()
        return redirect(url_for("entrar"))

    # ---------------- Página inicial ----------------

    @app.route("/")
    def inicio():
        mes = ler_mes(request.args.get("mes"))
        busca = request.args.get("q", "").strip()
        dados = ler_dados()
        hoje = date.today()

        lancamentos = dados["lancamentos"]
        do_mes = [l for _, l in filtrar(lancamentos, mes=mes)]
        do_anterior = [l for _, l in filtrar(lancamentos, mes=somar_meses(mes, -1))] if mes else None
        totais = totais_por_tipo(do_mes)
        barras = barras_das_categorias(dados, do_mes, mes, do_anterior)

        # Contas a pagar: as atrasadas e as que vencem nos próximos dias
        limite_aviso = (hoje + timedelta(days=DIAS_PARA_AVISAR)).isoformat()
        pendentes = contas_a_pagar(lancamentos)
        a_pagar = [par for par in pendentes if par[1]["data"] <= limite_aviso]

        # Resumo do mês, para o livro-caixa da tela do computador
        resumo = None
        if mes:
            despesas_do_mes = [l for l in do_mes if l["tipo"] == "despesa"]
            if mes == mes_atual():
                dias = hoje.day
            elif mes < mes_atual():
                dias = data_no_mes(mes, 31).day  # mês que já acabou: todos os dias dele
            else:
                dias = None  # mês que ainda não começou
            sobra = totais["receita"] - totais["despesa"]
            resumo = {
                "sobra": sobra,
                "guardado": sobra / totais["receita"] * 100 if totais["receita"] and sobra > 0 else None,
                "por_dia": totais["despesa"] / dias if dias else None,
                "maior": max(despesas_do_mes, key=lambda l: l["valor"], default=None),
                "quantidade": len(do_mes),
            }

        cartoes = []
        for conta in dados["contas"]:
            if conta["tipo"] == "cartao":
                aberta = fatura(lancamentos, conta, mes_da_fatura(conta, hoje.isoformat()))
                cartoes.append({"conta": conta, "fatura": aberta})

        return render_template(
            "inicio.html",
            mes=mes,
            busca=busca,
            anterior=somar_meses(mes, -1) if mes else None,
            seguinte=somar_meses(mes, 1) if mes else None,
            # O saldo atual não conta o que está agendado para depois de hoje nem o que falta pagar
            saldo=calcular_saldo(lancamentos, ate=hoje),
            previsto=calcular_saldo(lancamentos),
            totais=totais,
            variacao_despesas=variacao(totais["despesa"], totais_por_tipo(do_anterior)["despesa"])
            if mes else None,
            barras=barras,
            fatias=rosca(barras),
            evolucao=evolucao(lancamentos, mes or mes_atual()),
            itens=itens_da_lista(dados, filtrar(lancamentos, mes=mes, busca=busca)),
            a_pagar=itens_da_lista(dados, a_pagar[:5]),
            total_pendentes=len(pendentes),
            cartoes=cartoes,
            resumo=resumo,
            metas=[{"meta": m, **progresso_da_meta(m)} for m in dados["metas"]][:4],
            no_cofrinho=saldo_do_cofrinho(dados),
            guardado=total_guardado(dados),
        )

    # ---------------- Novo / editar / remover ----------------

    def campos_do_pedido():
        """O que a pessoa digitou, para mostrar de novo o formulário quando há erro."""
        f = request.form
        tipo = "receita" if f.get("tipo") == "receita" else "despesa"
        return {"tipo": tipo, "descricao": f.get("descricao", ""), "valor": f.get("valor", ""),
                "data": f.get("data", ""), "categoria": f.get(f"categoria_{tipo}"),
                "repetir": bool(f.get("repetir")), "parcelas": f.get("parcelas", ""),
                "conta": f.get("conta", ""), "pendente": bool(f.get("pendente"))}

    def ler_formulario(dados):
        """Monta o lançamento com o que veio do formulário. Lança ValueError."""
        campos = campos_do_pedido()
        valor = validar_valor(campos["valor"])
        data = ler_data(campos["data"])
        if campos["categoria"] not in categorias_do_tipo(dados, campos["tipo"]):
            raise ValueError("Escolha uma categoria da lista.")
        lancamento = {
            "tipo": campos["tipo"],
            "descricao": campos["descricao"].strip() or "Sem descrição",
            "valor": valor,
            "categoria": campos["categoria"],
            "data": data,
        }
        if campos["conta"]:
            if conta_por_id(dados, campos["conta"]) is None:
                raise ValueError("Essa conta não existe mais. Escolha outra.")
            lancamento["conta"] = campos["conta"]
        if campos["pendente"] and campos["tipo"] == "despesa":
            lancamento["pendente"] = True
        return lancamento

    def ler_parcelas():
        texto = request.form.get("parcelas", "").strip()
        if texto in ("", "1"):
            return 1
        if not texto.isdigit() or not 2 <= int(texto) <= MAXIMO_PARCELAS:
            raise ValueError(f"O número de parcelas precisa ser de 1 a {MAXIMO_PARCELAS}.")
        return int(texto)

    def mostrar_formulario(dados, campos, indice=None, lancamento=None, erro=None):
        categorias = {tipo: [(c, icone_da_categoria(dados, c)) for c in categorias_do_tipo(dados, tipo)]
                      for tipo in TIPOS}
        return render_template(
            "formulario.html", campos=campos, categorias=categorias, contas=dados["contas"],
            indice=indice, chave=request.values.get("c"),
            recorrente=lancamento is not None and recorrente_do_lancamento(dados, lancamento) is not None,
            parcela=lancamento.get("parcela") if lancamento else None,
            voltar=request.values.get("voltar", ""), erro=erro, maximo_parcelas=MAXIMO_PARCELAS)

    @app.get("/novo")
    def novo():
        tipo = "receita" if request.args.get("tipo") == "receita" else "despesa"
        campos = {"tipo": tipo, "descricao": "", "valor": "", "data": date.today().isoformat(),
                  "categoria": None, "repetir": False, "parcelas": "", "conta": "",
                  "pendente": request.args.get("pendente") == "1"}
        return mostrar_formulario(ler_dados(), campos)

    @app.post("/novo")
    def criar():
        with dados_do_arquivo() as dados:
            try:
                lancamento = ler_formulario(dados)
                parcelas = ler_parcelas() if lancamento["tipo"] == "despesa" else 1
                if parcelas > 1 and request.form.get("repetir"):
                    raise ValueError("Uma compra parcelada não pode também se repetir todo mês.")
                if parcelas > 1:
                    criar_parcelas(dados, lancamento, parcelas)
                else:
                    dados["lancamentos"].append(lancamento)
                    if request.form.get("repetir"):
                        criar_recorrente(dados, lancamento)
            except ValueError as erro:
                return mostrar_formulario(dados, campos_do_pedido(), erro=str(erro))
            if salvar(dados):
                tipo = lancamento["tipo"].capitalize()
                if parcelas > 1:
                    flash(f"{tipo} adicionada em {parcelas} parcelas: {lancamento['descricao']}.", "ok")
                else:
                    flash(f"{tipo} adicionada: {lancamento['descricao']}.", "ok")
        return redirect(url_for("inicio", mes=voltar_para(lancamento["data"])))

    @app.get("/editar/<int:indice>")
    def editar(indice):
        dados = ler_dados()
        l = achar_lancamento(dados, indice)
        if l is None:
            return redirect(url_for("inicio", mes=voltar_para()))
        campos = {"tipo": l["tipo"], "descricao": l["descricao"], "valor": formatar_numero(l["valor"]),
                  "data": l["data"], "categoria": l["categoria"], "conta": l.get("conta", ""),
                  "pendente": esta_pendente(l)}
        return mostrar_formulario(dados, campos, indice=indice, lancamento=l)

    @app.post("/editar/<int:indice>")
    def salvar_edicao(indice):
        with dados_do_arquivo() as dados:
            antigo = achar_lancamento(dados, indice)
            if antigo is None:
                return redirect(url_for("inicio", mes=voltar_para()))
            recorrente = recorrente_do_lancamento(dados, antigo)
            try:
                lancamento = ler_formulario(dados)
            except ValueError as erro:
                return mostrar_formulario(dados, campos_do_pedido(), indice=indice, lancamento=antigo,
                                          erro=str(erro))
            manter_extras(antigo, lancamento, CAMPOS_DE_LIGACAO)
            dados["lancamentos"][indice] = lancamento
            if recorrente and request.form.get("proximos"):
                atualizar_recorrente(recorrente, lancamento)
            if salvar(dados):
                flash("Lançamento atualizado.", "ok")
        return redirect(url_for("inicio", mes=voltar_para(lancamento["data"])))

    @app.post("/remover/<int:indice>")
    def remover(indice):
        with dados_do_arquivo() as dados:
            l = achar_lancamento(dados, indice)
            if l is not None:
                if l.get("compra") and request.form.get("seguintes"):
                    pares = parcelas_seguintes(dados, l)
                else:
                    pares = [(indice, l)]
                removidos = [item for _, item in pares]
                for posicao in sorted((i for i, _ in pares), reverse=True):
                    dados["lancamentos"].pop(posicao)

                parado = None
                recorrente = recorrente_do_lancamento(dados, l)
                if recorrente and request.form.get("parar"):
                    parar_recorrente(dados, recorrente)
                    parado = recorrente

                if salvar(dados):
                    guardar_para_desfazer(removidos, parado)
                    if len(removidos) > 1:
                        texto = f"{len(removidos)} parcelas de \"{l['descricao']}\" foram removidas."
                    else:
                        texto = f"\"{l['descricao']}\" foi removido."
                    flash(texto, "desfazer" if "desfazer" in session else "ok")
        return redirect(url_for("inicio", mes=voltar_para()))

    def guardar_para_desfazer(removidos, recorrente):
        """Guarda o que foi removido no cookie, para o botão "Desfazer".
        Se for coisa demais para o cookie (muitas parcelas), não há desfazer."""
        session.pop("desfazer", None)
        guardado = {"lancamentos": removidos, "recorrente": recorrente}
        if len(json.dumps(guardado, ensure_ascii=False)) <= TAMANHO_MAXIMO_DESFAZER:
            session["desfazer"] = guardado

    @app.post("/desfazer")
    def desfazer():
        guardado = session.pop("desfazer", None)
        if not guardado:
            flash("Não há nada para desfazer.", "info")
            return redirect(url_for("inicio", mes=voltar_para()))
        with dados_do_arquivo() as dados:
            existentes = {chave_do_lancamento(l) for l in dados["lancamentos"]}
            for l in guardado["lancamentos"]:
                if chave_do_lancamento(l) not in existentes:
                    dados["lancamentos"].append(l)
            r = guardado.get("recorrente")
            if r and all(x["id"] != r["id"] for x in dados["recorrentes"]):
                dados["recorrentes"].append(r)
            if salvar(dados):
                flash("Pronto, voltou para a lista.", "ok")
        return redirect(url_for("inicio", mes=voltar_para()))

    # ---------------- Contas a pagar ----------------

    @app.get("/pagar")
    def pagar():
        dados = ler_dados()
        return render_template("pagar.html", itens=itens_da_lista(dados, contas_a_pagar(dados["lancamentos"])))

    @app.post("/pagar/<int:indice>")
    def marcar_como_pago(indice):
        with dados_do_arquivo() as dados:
            l = achar_lancamento(dados, indice)
            if l is not None:
                marcar_pago(l)
                if salvar(dados):
                    flash(f"\"{l['descricao']}\" foi paga e já entrou no saldo.", "ok")
        if request.form.get("de") == "pagar":
            return redirect(url_for("pagar"))
        return redirect(url_for("inicio", mes=voltar_para()))

    # ---------------- Contas e cartões ----------------

    @app.route("/contas", methods=["GET", "POST"])
    def contas():
        with dados_do_arquivo() as dados:
            erro = None
            campos = {"nome": "", "tipo": "corrente", "fechamento": "", "vencimento": "", "limite": ""}
            if request.method == "POST":
                campos = {k: request.form.get(k, "").strip() for k in campos}
                try:
                    fechamento = vencimento = limite = None
                    if campos["tipo"] == "cartao":
                        fechamento = ler_dia(campos["fechamento"], "fechamento")
                        vencimento = ler_dia(campos["vencimento"], "vencimento")
                        limite = validar_valor(campos["limite"]) if campos["limite"] else None
                    conta = criar_conta(dados, campos["nome"], campos["tipo"], fechamento, vencimento, limite)
                except ValueError as e:
                    erro = str(e)
                else:
                    if salvar(dados):
                        flash(f"\"{conta['nome']}\" criada. Agora dá para escolhê-la ao lançar.", "ok")
                    return redirect(url_for("contas"))

            hoje = date.today()
            lista = []
            for conta in dados["contas"]:
                item = {"conta": conta, "nome_do_tipo": TIPOS_DE_CONTA[conta["tipo"]]}
                if conta["tipo"] == "cartao":
                    item["fatura"] = fatura(dados["lancamentos"], conta, mes_da_fatura(conta, hoje.isoformat()))
                    item["disponivel"] = limite_disponivel(dados["lancamentos"], conta, hoje)
                else:
                    item["saldo"] = saldo_da_conta(dados["lancamentos"], conta, hoje)
                lista.append(item)
            return render_template("contas.html", lista=lista, campos=campos, erro=erro,
                                   tipos=TIPOS_DE_CONTA)

    @app.get("/contas/<identificador>")
    def conta(identificador):
        dados = ler_dados()
        c = conta_por_id(dados, identificador)
        if c is None:
            abort(404)
        if c["tipo"] == "cartao":
            mes = request.args.get("fatura")
            if not (mes and _FORMATO_MES.fullmatch(mes)):
                mes = mes_da_fatura(c, date.today().isoformat())
            f = fatura(dados["lancamentos"], c, mes)
            return render_template("conta.html", conta=c, fatura=f, itens=itens_da_lista(dados, f["itens"]),
                                   anterior=somar_meses(mes, -1), seguinte=somar_meses(mes, 1),
                                   disponivel=limite_disponivel(dados["lancamentos"], c))
        pares = [(i, l) for i, l in filtrar(dados["lancamentos"]) if l.get("conta") == c["id"]]
        return render_template("conta.html", conta=c, fatura=None, itens=itens_da_lista(dados, pares[:200]),
                               saldo=saldo_da_conta(dados["lancamentos"], c))

    @app.post("/contas/<identificador>/remover")
    def remover_conta_web(identificador):
        with dados_do_arquivo() as dados:
            c = conta_por_id(dados, identificador)
            if c is not None:
                remover_conta(dados, c)
                if salvar(dados):
                    flash(f"\"{c['nome']}\" foi removida. Os lançamentos dela continuam na lista.", "ok")
        return redirect(url_for("contas"))

    # ---------------- Metas de economia ----------------

    @app.route("/metas", methods=["GET", "POST"])
    def metas():
        with dados_do_arquivo() as dados:
            erro = None
            campos = {"nome": "", "alvo": "", "prazo": ""}
            if request.method == "POST":
                campos = {k: request.form.get(k, "").strip() for k in campos}
                try:
                    alvo = validar_valor(campos["alvo"])
                    prazo = campos["prazo"] or None
                    if prazo and not _FORMATO_MES.fullmatch(prazo):
                        raise ValueError("Escolha o mês do prazo.")
                    meta = criar_meta(dados, campos["nome"], alvo, prazo)
                except ValueError as e:
                    erro = str(e)
                else:
                    if salvar(dados):
                        flash(f"Meta \"{meta['nome']}\" criada.", "ok")
                    return redirect(url_for("metas"))
            lista = [{"meta": m, **progresso_da_meta(m)} for m in dados["metas"]]
            return render_template("metas.html", lista=lista, campos=campos, erro=erro,
                                   mes_minimo=mes_atual())

    @app.post("/metas/<identificador>")
    def movimentar(identificador):
        with dados_do_arquivo() as dados:
            meta = meta_por_id(dados, identificador)
            if meta is None:
                abort(404)
            acao = request.form.get("acao")
            try:
                if acao == "remover":
                    dados["metas"].remove(meta)
                    mensagem = f"Meta \"{meta['nome']}\" removida."
                else:
                    valor = validar_valor(request.form.get("valor", ""))
                    movimentar_meta(meta, -valor if acao == "retirar" else valor)
                    if acao == "retirar":
                        mensagem = f"{formatar_reais(valor)} retirados de \"{meta['nome']}\"."
                    elif meta["guardado"] >= meta["alvo"]:
                        mensagem = f"Meta \"{meta['nome']}\" alcançada!"
                    else:
                        mensagem = f"{formatar_reais(valor)} guardados em \"{meta['nome']}\"."
            except ValueError as erro:
                flash(str(erro), "erro")
            else:
                if salvar(dados):
                    flash(mensagem, "ok")
        return redirect(url_for("metas"))

    # ---------------- Cofrinho ----------------

    @app.route("/cofrinho", methods=["GET", "POST"])
    def cofrinho():
        with dados_do_arquivo() as dados:
            erro = None
            campos = {"valor": "", "descricao": ""}
            if request.method == "POST":
                campos = {k: request.form.get(k, "").strip() for k in campos}
                retirar = request.form.get("acao") == "retirar"
                try:
                    valor = validar_valor(campos["valor"])
                    movimentar_cofrinho(dados, -valor if retirar else valor, campos["descricao"])
                except ValueError as e:
                    erro = str(e)
                else:
                    if salvar(dados):
                        if retirar:
                            flash(f"{formatar_reais(valor)} retirados do cofrinho.", "ok")
                        else:
                            flash(f"{formatar_reais(valor)} guardados no cofrinho.", "ok")
                    return redirect(url_for("cofrinho"))

            movimentos = movimentos_do_cofrinho(dados)
            este_mes = sum(m["valor"] for m in movimentos if m["data"][:7] == mes_atual())
            return render_template(
                "cofrinho.html", erro=erro, campos=campos, movimentos=movimentos,
                saldo=saldo_do_cofrinho(dados), este_mes=round(este_mes, 2),
                nas_metas=round(sum(m["guardado"] for m in dados["metas"]), 2))

    @app.post("/cofrinho/<identificador>/apagar")
    def apagar_movimento(identificador):
        with dados_do_arquivo() as dados:
            try:
                movimento = desfazer_movimento(dados, identificador)
            except ValueError as erro:
                flash(str(erro), "erro")
            else:
                if salvar(dados):
                    flash(f"Movimento \"{movimento['descricao']}\" apagado.", "ok")
        return redirect(url_for("cofrinho"))

    # ---------------- Importar extrato ----------------

    @app.route("/importar", methods=["GET", "POST"])
    def importar():
        dados = ler_dados()
        if request.method == "GET":
            return render_template("importar.html", contas=dados["contas"], erro=None)
        arquivo_enviado = request.files.get("extrato")
        conta_escolhida = request.form.get("conta", "")
        try:
            if not arquivo_enviado or not arquivo_enviado.filename:
                raise ValueError("Escolha o arquivo do extrato.")
            itens = ler_extrato(arquivo_enviado.read(), arquivo_enviado.filename,
                                inverter=bool(request.form.get("inverter")))
        except ValueError as erro:
            return render_template("importar.html", contas=dados["contas"], erro=str(erro))
        for item in itens:
            item["repetido"] = parece_ja_lancado(dados, item)
            item["categoria"] = sugerir_categoria(dados, item["descricao"], item["tipo"])
        categorias = {tipo: categorias_do_tipo(dados, tipo) for tipo in TIPOS}
        return render_template("importar_revisar.html", itens=itens, categorias=categorias,
                               conta=conta_por_id(dados, conta_escolhida))

    @app.post("/importar/confirmar")
    def confirmar_importacao():
        with dados_do_arquivo() as dados:
            conta = conta_por_id(dados, request.form.get("conta", ""))
            novos = []
            for i in range(int(request.form.get("quantidade", 0) or 0)):
                if not request.form.get(f"incluir_{i}"):
                    continue
                tipo = "receita" if request.form.get(f"tipo_{i}") == "receita" else "despesa"
                categoria = request.form.get(f"categoria_{i}")
                try:
                    lancamento = {"tipo": tipo,
                                  "descricao": request.form.get(f"descricao_{i}", "").strip()[:80] or "Sem descrição",
                                  "valor": validar_valor(request.form.get(f"valor_{i}", "")),
                                  "categoria": categoria,
                                  "data": date.fromisoformat(request.form.get(f"data_{i}", "")).isoformat()}
                except ValueError:
                    continue
                if categoria not in categorias_do_tipo(dados, tipo):
                    continue
                if conta:
                    lancamento["conta"] = conta["id"]
                novos.append(lancamento)
            dados["lancamentos"].extend(novos)
            if novos and salvar(dados):
                flash(f"{len(novos)} lançamento(s) importado(s).", "ok")
            elif not novos:
                flash("Nenhum lançamento foi marcado para importar.", "info")
        return redirect(url_for("inicio", mes="todos"))

    # ---------------- Orçamentos, recorrentes, categorias ----------------

    @app.get("/mais")
    def mais():
        dados = ler_dados()
        totais = totais_por_mes(dados["lancamentos"])
        meses = [{"mes": m, "receita": totais[m]["receita"], "despesa": totais[m]["despesa"],
                  "saldo": totais[m]["receita"] - totais[m]["despesa"]}
                 for m in sorted(totais, reverse=True)]
        return render_template("mais.html", meses=meses, recorrentes=len(dados["recorrentes"]),
                               contas=len(dados["contas"]), metas=len(dados["metas"]),
                               no_cofrinho=saldo_do_cofrinho(dados),
                               pendentes=len(contas_a_pagar(dados["lancamentos"])))

    @app.route("/orcamentos", methods=["GET", "POST"])
    def orcamentos():
        with dados_do_arquivo() as dados:
            categorias = categorias_do_tipo(dados, "despesa")
            icones = {c: icone_da_categoria(dados, c) for c in categorias}
            if request.method == "GET":
                campos = {c: formatar_numero(dados["orcamentos"][c]) if c in dados["orcamentos"] else ""
                          for c in categorias}
                return render_template("orcamentos.html", campos=campos, erros={}, icones=icones)

            campos = {c: request.form.get(c, "").strip() for c in categorias}
            novos = {c: v for c, v in dados["orcamentos"].items() if c not in categorias}
            erros = {}
            for categoria, texto in campos.items():
                if not texto:
                    continue  # vazio = sem limite
                try:
                    limite = validar_valor(texto, aceitar_zero=True)
                except ValueError as erro:
                    erros[categoria] = str(erro)
                    continue
                if limite:
                    novos[categoria] = limite
            if erros:
                return render_template("orcamentos.html", campos=campos, erros=erros, icones=icones)
            dados["orcamentos"] = novos
            if salvar(dados):
                flash("Orçamentos salvos.", "ok")
        return redirect(url_for("inicio"))

    @app.get("/recorrentes")
    def recorrentes():
        dados = ler_dados()
        lista = sorted(dados["recorrentes"], key=lambda r: (r["dia"], r["descricao"]))
        return render_template("recorrentes.html", recorrentes=lista,
                               icones={r["id"]: icone_da_categoria(dados, r["categoria"]) for r in lista})

    @app.post("/recorrentes/<identificador>/parar")
    def parar(identificador):
        with dados_do_arquivo() as dados:
            for r in dados["recorrentes"]:
                if r["id"] == identificador:
                    parar_recorrente(dados, r)
                    if salvar(dados):
                        flash(f"\"{r['descricao']}\" não vai mais se repetir. "
                              "Os lançamentos já criados continuam na lista.", "ok")
                    break
        return redirect(url_for("recorrentes"))

    @app.route("/categorias", methods=["GET", "POST"])
    def categorias():
        with dados_do_arquivo() as dados:
            if request.method == "POST":
                tipo = request.form.get("tipo")
                if tipo not in TIPOS:
                    abort(400)
                nome = request.form.get("nome", "")
                acao = request.form.get("acao")
                try:
                    if acao == "remover":
                        remover_categoria(dados, tipo, nome)
                        mensagem = f"Categoria \"{nome}\" removida."
                    elif acao == "icone":
                        if nome not in categorias_do_tipo(dados, tipo):
                            raise ValueError("Essa categoria não existe mais.")
                        definir_icone(dados, nome, request.form.get("icone", ""))
                        mensagem = f"Ícone de \"{nome}\" trocado."
                    else:
                        nome = adicionar_categoria(dados, tipo, nome)
                        icone = request.form.get("icone")
                        if icone:
                            definir_icone(dados, nome, icone)
                        mensagem = f"Categoria \"{nome}\" criada."
                except ValueError as erro:
                    flash(str(erro), "erro")
                else:
                    if salvar(dados):
                        flash(mensagem, "ok")
                return redirect(url_for("categorias"))
            listas = {tipo: [(c, icone_da_categoria(dados, c)) for c in categorias_do_tipo(dados, tipo)]
                      for tipo in TIPOS}
            return render_template("categorias.html", listas=listas, icones=ICONES_PARA_ESCOLHER)

    # ---------------- Exportar, ícone, desenho da cédula ----------------

    @app.get("/exportar")
    def exportar():
        mes = ler_mes(request.args.get("mes"))
        lancamentos = [l for _, l in filtrar(ler_dados()["lancamentos"], mes=mes)]
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "lancamentos.csv"
            exportar_csv(lancamentos, caminho)
            conteudo = caminho.read_bytes()
        nome = f"lancamentos-{mes or 'todos'}.csv"
        return Response(conteudo, mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    @app.get("/icone.png")
    @app.get("/apple-touch-icon.png")  # o iPhone procura neste endereço sozinho
    def icone():
        return Response(png_do_icone, mimetype="image/png", headers={"Cache-Control": "max-age=604800"})

    @app.get("/guilhoche.svg")
    def guilhoche():
        return Response(svg_do_guilhoche, mimetype="image/svg+xml",
                        headers={"Cache-Control": "max-age=604800"})

    @app.get("/manifest.webmanifest")
    def manifesto():
        return app.response_class(json.dumps({
            "name": "Controle de Gastos", "short_name": "Gastos", "start_url": "/",
            "display": "standalone", "background_color": "#edf0eb", "theme_color": "#2b5f8a",
            "icons": [{"src": "/icone.png", "sizes": "180x180", "type": "image/png"}],
        }), mimetype="application/manifest+json")

    @app.errorhandler(413)
    def arquivo_grande_demais(_erro):
        flash("O arquivo é grande demais (máximo de 2 MB).", "erro")
        return redirect(url_for("importar"))

    @app.context_processor
    def funcoes_das_paginas():
        return {"formatar_reais": formatar_reais, "formatar_saldo": formatar_saldo,
                "formatar_data": formatar_data, "formatar_mes": formatar_mes,
                "formatar_mes_curto": formatar_mes_curto, "rotulo_dia": rotulo_dia,
                "formatar_variacao": formatar_variacao, "quando_vence": quando_vence,
                "formatar_numero": formatar_numero}

    return app


def endereco_na_rede():
    """O IP deste computador no Wi-Fi, que é o endereço que o celular deve abrir."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # não envia nada: só escolhe a placa de rede
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def abrir_janela(endereco):
    """Abre a página numa janela só dela, maximizada e sem barra de endereço
    (o "modo app" do Edge ou do Chrome), para parecer um programa. Sem nenhum
    dos dois, abre no navegador padrão. F11 deixa em tela cheia de verdade."""
    candidatos = [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ]
    for caminho in map(os.path.expandvars, candidatos):
        if os.path.isfile(caminho):
            subprocess.Popen([caminho, f"--app={endereco}", "--start-maximized"])
            return
    webbrowser.open(endereco)


def pedir_senha_nova():
    print("Crie uma senha para abrir a página no celular (ela não aparece enquanto você digita).")
    while True:
        senha = getpass("Senha: ")
        if len(senha) < 4:
            print("Use pelo menos 4 caracteres.")
        elif getpass("Repita a senha: ") != senha:
            print("As duas senhas não são iguais. Tente de novo.")
        else:
            return senha


def main():
    config = carregar_config()
    nova_senha = "--nova-senha" in sys.argv[1:]
    if nova_senha:
        # Chave nova também: quem entrou com a senha antiga precisa digitar a nova
        config.pop("chave", None)

    senha = os.environ.get("CONTROLE_SENHA") or (None if nova_senha else config.get("senha"))
    if not senha:
        senha = config["senha"] = resumo_da_senha(pedir_senha_nova())
        print("Senha guardada. Ela não será pedida de novo neste computador.")
    config.setdefault("chave", secrets.token_hex(32))
    salvar_config(config)
    app = criar_app(senha, chave=config["chave"])

    endereco = f"http://localhost:{PORTA}"
    print()
    print("  Controle de Gastos no navegador")
    print(f"  No celular (mesmo Wi-Fi):  http://{endereco_na_rede()}:{PORTA}")
    print(f"  Neste computador:          {endereco}")
    print("  Para trocar a senha:       python app_web.py --nova-senha")
    print("  Para fechar, aperte Ctrl+C.")
    print()
    if "--sem-navegador" not in sys.argv[1:]:
        threading.Timer(1.5, abrir_janela, [endereco]).start()
    try:
        app.run(host="0.0.0.0", port=PORTA)
    except OSError:
        print(f"A porta {PORTA} já está em uso. O programa já está aberto em outra janela?")
        sys.exit(1)


if __name__ == "__main__":
    main()
