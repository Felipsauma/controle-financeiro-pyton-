"""
Controle de Gastos Pessoais - versão para o navegador (Flask)
-------------------------------------------------------------
As mesmas funções das outras versões, numa página feita para o celular:
saldo, lançamentos (com busca, edição e remoção), orçamentos, gráficos,
lançamentos recorrentes, categorias e exportação para o Excel.

O programa roda no computador e o celular abre a página pelo Wi-Fi. Como
qualquer aparelho da rede consegue abrir o endereço, a página pede senha.

As regras (salvar, calcular, validar...) ficam em financas.py e são as
mesmas das outras versões. Os dados ficam em "gastos.json".

Como rodar:
    pip install flask
    python app_web.py

Depois abra no celular o endereço que aparece no terminal (o celular
precisa estar no mesmo Wi-Fi). No iPhone, em Compartilhar > "Adicionar à
Tela de Início", a página ganha um ícone e abre como um app.

A senha pode vir da variável de ambiente CONTROLE_SENHA. Se não vier, o
programa pergunta ao abrir.
"""

import hashlib
import json
import os
import re
import secrets
import socket
import struct
import tempfile
import threading
import time
import zlib
from contextlib import contextmanager
from datetime import date, timedelta
from getpass import getpass
from hmac import compare_digest
from pathlib import Path

from flask import Flask, Response, abort, flash, redirect, render_template, request, session, url_for

from financas import (
    TIPOS,
    DadosAlteradosPorFora,
    DadosCorrompidos,
    adicionar_categoria,
    atualizar_recorrente,
    calcular_saldo,
    carregar_dados,
    categorias_do_tipo,
    criar_recorrente,
    eh_futuro,
    exportar_csv,
    filtrar,
    formatar_data,
    formatar_mes,
    formatar_mes_curto,
    formatar_numero,
    formatar_reais,
    gerar_recorrentes,
    mes_atual,
    parar_recorrente,
    recorrente_do_lancamento,
    remover_categoria,
    salvar_dados,
    situacao_orcamento,
    somar_meses,
    totais_por_categoria,
    totais_por_mes,
    totais_por_tipo,
    validar_data,
    validar_valor,
)

PORTA = 5000

# As mesmas cores de categoria da versão com janela
CORES_CATEGORIAS = ["#10a37f", "#3b82f6", "#f59e0b", "#8b5cf6", "#ef4444", "#ec4899", "#64748b"]

DIAS_DA_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def cor_da_categoria(categoria, categorias):
    if categoria in categorias:
        return CORES_CATEGORIAS[categorias.index(categoria) % len(CORES_CATEGORIAS)]
    return CORES_CATEGORIAS[-1]


def formatar_saldo(valor):
    """Saldo com o sinal de menos tipográfico (fica mais bonito na tela)."""
    return f"− {formatar_reais(-valor)}" if valor < 0 else formatar_reais(valor)


def rotulo_dia(iso):
    """'2026-10-15' -> 'Hoje', 'Ontem' ou 'qui, 15/10/2026' (títulos da lista)."""
    dia = date.fromisoformat(iso)
    diferenca = (date.today() - dia).days
    if diferenca == 0:
        return "Hoje"
    if diferenca == 1:
        return "Ontem"
    return f"{DIAS_DA_SEMANA[dia.weekday()]}, {formatar_data(iso)}"


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


# ----------------------------------------------------------------------
# Dados para os gráficos da página inicial
# ----------------------------------------------------------------------

def barras_das_categorias(dados, lancamentos_do_mes, mes):
    """Despesas por categoria, comparadas com o orçamento quando há um mês escolhido."""
    totais = totais_por_categoria(lancamentos_do_mes, "despesa")
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
        if situacao == "sem":
            # Sem orçamento: barra proporcional à maior categoria
            proporcao = gasto / maior
            porcentagem = f"{gasto / total_geral * 100:.1f}".replace(".", ",")
            texto = f"{formatar_reais(gasto)} · {porcentagem}%"
        else:
            # Com orçamento: barra mostra quanto do limite já foi usado
            proporcao = min(gasto / limite, 1)
            texto = f"{formatar_reais(gasto)} de {formatar_reais(limite)}"
            if situacao == "alerta":
                texto = f"Quase no limite · {texto}"
            elif situacao == "estourado":
                texto = f"Passou {formatar_reais(gasto - limite)} · {texto}"
        barras.append({"nome": categoria, "situacao": situacao, "texto": texto,
                       "cor": cor_da_categoria(categoria, lista_categorias),
                       "largura": round(proporcao * 100, 1)})
    return barras


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
# Ícone da tela de início (um PNG desenhado sem nenhuma biblioteca)
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
    """Fundo verde com três barras brancas subindo. O iPhone arredonda os cantos sozinho."""
    verde, branco = (16, 163, 127), (255, 255, 255)
    barras = [(0.22, 0.36, 0.56), (0.43, 0.57, 0.40), (0.64, 0.78, 0.24)]  # (esquerda, direita, topo)

    def pixel(x, y):
        fx, fy = x / tamanho, y / tamanho
        for esquerda, direita, topo in barras:
            if esquerda <= fx < direita and topo <= fy < 0.78:
                return branco
        return verde

    return _png(tamanho, tamanho, pixel)


# ----------------------------------------------------------------------
# O site
# ----------------------------------------------------------------------

def criar_app(senha, arquivo=None):
    """Cria o site. 'arquivo' é o JSON dos dados (os testes usam um temporário)."""
    app = Flask(__name__)
    app.config.update(
        # Chave nova a cada vez que o programa abre: quem entrou antes precisa digitar a senha de novo
        SECRET_KEY=secrets.token_bytes(32),
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
    )
    # O Flask atende vários pedidos ao mesmo tempo; a trava faz um ler-alterar-salvar por vez
    trava = threading.Lock()
    png_do_icone = desenhar_icone()

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

    # ---------------- Senha ----------------

    @app.before_request
    def pedir_senha():
        if request.endpoint in ("entrar", "icone", "manifesto", "static") or session.get("entrou"):
            return None
        return redirect(url_for("entrar"))

    @app.route("/entrar", methods=["GET", "POST"])
    def entrar():
        erro = None
        if request.method == "POST":
            if compare_digest(request.form.get("senha", "").encode(), senha.encode()):
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

        lancamentos = dados["lancamentos"]
        do_mes = [l for _, l in filtrar(lancamentos, mes=mes)]
        itens = [{"indice": i, "chave": chave_do_lancamento(l), "l": l, "futuro": eh_futuro(l)}
                 for i, l in filtrar(lancamentos, mes=mes, busca=busca)]
        return render_template(
            "inicio.html",
            mes=mes,
            busca=busca,
            anterior=somar_meses(mes, -1) if mes else None,
            seguinte=somar_meses(mes, 1) if mes else None,
            # O saldo atual não conta o que está agendado para depois de hoje
            saldo=calcular_saldo(lancamentos, ate=date.today()),
            previsto=calcular_saldo(lancamentos),
            totais=totais_por_tipo(do_mes),
            barras=barras_das_categorias(dados, do_mes, mes),
            evolucao=evolucao(lancamentos, mes or mes_atual()),
            itens=itens,
        )

    # ---------------- Novo / editar / remover ----------------

    def campos_do_pedido():
        """O que a pessoa digitou, para mostrar de novo o formulário quando há erro."""
        f = request.form
        tipo = "receita" if f.get("tipo") == "receita" else "despesa"
        return {"tipo": tipo, "descricao": f.get("descricao", ""), "valor": f.get("valor", ""),
                "data": f.get("data", ""), "categoria": f.get(f"categoria_{tipo}"),
                "repetir": bool(f.get("repetir"))}

    def ler_formulario(dados):
        """Monta o lançamento com o que veio do formulário. Lança ValueError."""
        campos = campos_do_pedido()
        valor = validar_valor(campos["valor"])
        data = ler_data(campos["data"])
        if campos["categoria"] not in categorias_do_tipo(dados, campos["tipo"]):
            raise ValueError("Escolha uma categoria da lista.")
        return {
            "tipo": campos["tipo"],
            "descricao": campos["descricao"].strip() or "Sem descrição",
            "valor": valor,
            "categoria": campos["categoria"],
            "data": data,
        }

    def mostrar_formulario(dados, campos, indice=None, recorrente=False, erro=None):
        categorias = {tipo: categorias_do_tipo(dados, tipo) for tipo in TIPOS}
        return render_template("formulario.html", campos=campos, categorias=categorias,
                               indice=indice, chave=request.values.get("c"), recorrente=recorrente,
                               voltar=request.values.get("voltar", ""), erro=erro)

    @app.get("/novo")
    def novo():
        tipo = "receita" if request.args.get("tipo") == "receita" else "despesa"
        campos = {"tipo": tipo, "descricao": "", "valor": "", "data": date.today().isoformat(),
                  "categoria": None, "repetir": False}
        return mostrar_formulario(ler_dados(), campos)

    @app.post("/novo")
    def criar():
        with dados_do_arquivo() as dados:
            try:
                lancamento = ler_formulario(dados)
            except ValueError as erro:
                return mostrar_formulario(dados, campos_do_pedido(), erro=str(erro))
            dados["lancamentos"].append(lancamento)
            if request.form.get("repetir"):
                criar_recorrente(dados, lancamento)
            if salvar(dados):
                flash(f"{lancamento['tipo'].capitalize()} adicionada: {lancamento['descricao']}.", "ok")
        return redirect(url_for("inicio", mes=voltar_para(lancamento["data"])))

    @app.get("/editar/<int:indice>")
    def editar(indice):
        dados = ler_dados()
        l = achar_lancamento(dados, indice)
        if l is None:
            return redirect(url_for("inicio", mes=voltar_para()))
        campos = {"tipo": l["tipo"], "descricao": l["descricao"], "valor": formatar_numero(l["valor"]),
                  "data": l["data"], "categoria": l["categoria"]}
        return mostrar_formulario(dados, campos, indice=indice,
                                  recorrente=recorrente_do_lancamento(dados, l) is not None)

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
                return mostrar_formulario(dados, campos_do_pedido(), indice=indice,
                                          recorrente=recorrente is not None, erro=str(erro))
            if antigo.get("recorrente"):
                lancamento["recorrente"] = antigo["recorrente"]
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
                dados["lancamentos"].pop(indice)
                recorrente = recorrente_do_lancamento(dados, l)
                if recorrente and request.form.get("parar"):
                    parar_recorrente(dados, recorrente)
                if salvar(dados):
                    flash(f"\"{l['descricao']}\" foi removido.", "ok")
        return redirect(url_for("inicio", mes=voltar_para()))

    # ---------------- Orçamentos, recorrentes, categorias ----------------

    @app.get("/mais")
    def mais():
        dados = ler_dados()
        totais = totais_por_mes(dados["lancamentos"])
        meses = [{"mes": m, "receita": totais[m]["receita"], "despesa": totais[m]["despesa"],
                  "saldo": totais[m]["receita"] - totais[m]["despesa"]}
                 for m in sorted(totais, reverse=True)]
        return render_template("mais.html", meses=meses, recorrentes=len(dados["recorrentes"]))

    @app.route("/orcamentos", methods=["GET", "POST"])
    def orcamentos():
        with dados_do_arquivo() as dados:
            categorias = categorias_do_tipo(dados, "despesa")
            if request.method == "GET":
                campos = {c: formatar_numero(dados["orcamentos"][c]) if c in dados["orcamentos"] else ""
                          for c in categorias}
                return render_template("orcamentos.html", campos=campos, erros={})

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
                return render_template("orcamentos.html", campos=campos, erros=erros)
            dados["orcamentos"] = novos
            if salvar(dados):
                flash("Orçamentos salvos.", "ok")
        return redirect(url_for("inicio"))

    @app.get("/recorrentes")
    def recorrentes():
        dados = ler_dados()
        lista = sorted(dados["recorrentes"], key=lambda r: (r["dia"], r["descricao"]))
        return render_template("recorrentes.html", recorrentes=lista)

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
                try:
                    if request.form.get("acao") == "remover":
                        remover_categoria(dados, tipo, nome)
                        mensagem = f"Categoria \"{nome}\" removida."
                    else:
                        nome = adicionar_categoria(dados, tipo, nome)
                        mensagem = f"Categoria \"{nome}\" criada."
                except ValueError as erro:
                    flash(str(erro), "erro")
                else:
                    if salvar(dados):
                        flash(mensagem, "ok")
                return redirect(url_for("categorias"))
            listas = {tipo: categorias_do_tipo(dados, tipo) for tipo in TIPOS}
            return render_template("categorias.html", listas=listas)

    # ---------------- Exportar, ícone ----------------

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

    @app.get("/manifest.webmanifest")
    def manifesto():
        return app.response_class(json.dumps({
            "name": "Controle de Gastos", "short_name": "Gastos", "start_url": "/",
            "display": "standalone", "background_color": "#f3f5f9", "theme_color": "#10a37f",
            "icons": [{"src": "/icone.png", "sizes": "180x180", "type": "image/png"}],
        }), mimetype="application/manifest+json")

    @app.context_processor
    def funcoes_das_paginas():
        return {"formatar_reais": formatar_reais, "formatar_saldo": formatar_saldo,
                "formatar_data": formatar_data, "formatar_mes": formatar_mes,
                "formatar_mes_curto": formatar_mes_curto, "rotulo_dia": rotulo_dia}

    return app


def endereco_na_rede():
    """O IP deste computador no Wi-Fi, que é o endereço que o celular deve abrir."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # não envia nada: só escolhe a placa de rede
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main():
    senha = os.environ.get("CONTROLE_SENHA", "")
    while not senha:
        senha = getpass("Crie uma senha para abrir a página (ela não aparece enquanto você digita): ")
    app = criar_app(senha)

    print()
    print("  Controle de Gastos no navegador")
    print(f"  No celular (mesmo Wi-Fi):  http://{endereco_na_rede()}:{PORTA}")
    print(f"  Neste computador:          http://localhost:{PORTA}")
    print("  Para fechar, aperte Ctrl+C.")
    print()
    app.run(host="0.0.0.0", port=PORTA)


if __name__ == "__main__":
    main()
