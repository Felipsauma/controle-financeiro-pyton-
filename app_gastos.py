"""
Controle de Gastos Pessoais - versão com janela (Tkinter)
---------------------------------------------------------
Registra despesas (dinheiro que sai) e receitas (dinheiro que entra) e mostra:
  - o saldo e o total de receitas e despesas do mês escolhido;
  - a lista de lançamentos, com busca, edição (duplo clique) e remoção;
  - as despesas por categoria comparadas com o orçamento de cada uma;
  - um gráfico com a evolução dos últimos meses.

Lançamentos marcados como "Repetir todo mês" (salário, aluguel...) são
criados sozinhos quando o mês seguinte chega. As categorias podem ser
personalizadas em "Gerenciar categorias".

As regras (salvar, calcular, validar...) ficam em financas.py e são as
mesmas da versão de terminal. Os dados ficam em "gastos.json".

Como rodar:  python app_gastos.py
"""

import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

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

# ----------------------------------------------------------------------
# Visual: cores e fonte usadas em toda a janela
# ----------------------------------------------------------------------

FONTE = "Segoe UI"
FUNDO = "#f3f5f9"          # cinza bem claro atrás dos cartões
CARTAO = "#ffffff"
BORDA = "#e3e7ee"
TEXTO = "#1f2937"
TEXTO_SUAVE = "#6b7280"
LISTRA = "#f9fafb"         # linhas alternadas da tabela
ACENTO = "#10a37f"         # verde principal (também é a cor das receitas)
ACENTO_ESCURO = "#0c8a6b"
ACENTO_CLARO = "#e6f6f1"
PERIGO = "#dc2626"         # vermelho (cor das despesas)
PERIGO_ESCURO = "#b91c1c"
ALERTA = "#d97706"         # laranja: orçamento quase no limite

COR_TIPO = {"receita": ACENTO, "despesa": PERIGO}

# Cores das categorias de despesa, na ordem da lista de categorias (repetem se houver mais)
CORES_CATEGORIAS = ["#10a37f", "#3b82f6", "#f59e0b", "#8b5cf6", "#ef4444", "#ec4899", "#64748b"]


def cor_da_categoria(categoria, categorias):
    if categoria in categorias:
        return CORES_CATEGORIAS[categorias.index(categoria) % len(CORES_CATEGORIAS)]
    return CORES_CATEGORIAS[-1]


def formatar_saldo(valor):
    """Saldo com o sinal de menos tipográfico (fica mais bonito na janela)."""
    return f"− {formatar_reais(-valor)}" if valor < 0 else formatar_reais(valor)


def ativar_alta_resolucao():
    """No Windows, evita que o texto fique borrado em telas com zoom (125%, 150%...)."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (ImportError, AttributeError, OSError):
        pass  # outro sistema ou Windows antigo: segue normalmente


# ----------------------------------------------------------------------
# Janela principal
# ----------------------------------------------------------------------

class AppGastos(tk.Tk):
    def __init__(self):
        super().__init__()
        # Fator de zoom da tela (1.0 = 100%, 1.5 = 150%) para os tamanhos em pixels
        self.escala = self.winfo_fpixels("1i") / 96

        self.title("Controle de Gastos")
        largura = min(self.px(1080), self.winfo_screenwidth() - 40)
        altura = min(self.px(740), self.winfo_screenheight() - 80)
        self.geometry(f"{largura}x{altura}")
        self.minsize(min(self.px(920), largura), min(self.px(640), altura))
        self.configure(bg=FUNDO)

        self.mes = mes_atual()   # mês mostrado na tela; None = todos os meses
        self.editando = None     # posição do lançamento sendo editado (None = adicionando)
        self.dados = self.carregar()

        self.configurar_estilos()
        self.criar_cabecalho()
        self.criar_conteudo()
        self.mudar_tipo("despesa")
        self.atualizar_tudo()

    def px(self, valor):
        """Ajusta um tamanho em pixels ao zoom da tela."""
        return int(valor * self.escala)

    # ---------------- Dados ----------------

    def carregar(self):
        """Carrega os dados e cria os lançamentos recorrentes que venceram."""
        try:
            dados = carregar_dados()
        except DadosCorrompidos as erro:
            dados = erro.dados
            backup = erro.backup.name
            if erro.ignorados:
                texto = (f"{erro.ignorados} item(ns) inválido(s) nos dados salvos foram ignorados.\n\n"
                         f"Nada foi apagado: o arquivo original foi copiado para \"{backup}\".")
            else:
                texto = ("Não foi possível ler os dados salvos.\n\n"
                         f"Nada foi apagado: o arquivo antigo foi guardado como \"{backup}\" "
                         "e o programa começou com uma lista vazia.")
            self.after(300, lambda: messagebox.showwarning("Arquivo corrompido", texto))

        criados = gerar_recorrentes(dados)
        if criados:
            try:
                salvar_dados(dados)
            except OSError:
                pass  # os lançamentos estão na tela; o próximo salvamento tenta de novo
            self.after(300, lambda: messagebox.showinfo(
                "Lançamentos recorrentes",
                f"{criados} lançamento(s) que se repetem todo mês foram adicionados automaticamente."))
        return dados

    def salvar(self):
        """Salva e atualiza a tela. Se a versão de terminal mexeu no arquivo enquanto
        a janela estava aberta, pergunta qual das duas versões manter."""
        try:
            salvar_dados(self.dados)
        except DadosAlteradosPorFora:
            manter = messagebox.askyesno(
                "Dados alterados em outro lugar",
                "Os dados foram alterados por outro programa enquanto esta janela estava aberta "
                "(a versão de terminal está aberta?).\n\n"
                "Sim: salvar a versão desta janela e descartar as mudanças feitas lá.\n"
                "Não: recarregar o arquivo e descartar a última alteração feita aqui.",
                icon="warning")
            if manter:
                salvar_dados(self.dados, forcar=True)
            else:
                self.dados = self.carregar()
                self.limpar_formulario()  # as posições dos lançamentos podem ter mudado
                self.mudar_tipo(self.tipo)
        except OSError as erro:
            messagebox.showerror("Erro ao salvar", f"Não foi possível salvar os dados.\n\n{erro}")
        self.atualizar_tudo()

    def lancamentos_visiveis(self):
        """Pares (posição, lançamento) do mês escolhido que batem com a busca."""
        return filtrar(self.dados["lancamentos"], mes=self.mes, busca=self.var_busca.get())

    def lancamentos_do_mes(self):
        return [l for _, l in filtrar(self.dados["lancamentos"], mes=self.mes)]

    # ---------------- Estilos ----------------

    def configurar_estilos(self):
        estilo = ttk.Style(self)
        estilo.theme_use("clam")  # tema mais fácil de personalizar

        estilo.configure(".", font=(FONTE, 10), background=CARTAO, foreground=TEXTO)
        estilo.configure("Suave.TLabel", foreground=TEXTO_SUAVE, font=(FONTE, 9))
        estilo.configure("TituloCartao.TLabel", font=(FONTE, 13, "bold"))
        estilo.configure("Indicador.TLabel", font=(FONTE, 18, "bold"))

        # Campos de texto: borda fina que fica verde quando o campo está em foco
        campo = dict(fieldbackground=CARTAO, bordercolor=BORDA, lightcolor=BORDA,
                     darkcolor=BORDA, padding=self.px(7))
        foco = dict(bordercolor=[("focus", ACENTO)], lightcolor=[("focus", ACENTO)])
        estilo.configure("TEntry", **campo)
        estilo.map("TEntry", **foco)
        estilo.configure("TCombobox", background=CARTAO, arrowcolor=TEXTO_SUAVE, **campo)
        estilo.map("TCombobox", fieldbackground=[("readonly", CARTAO)],
                   selectbackground=[("readonly", CARTAO)],
                   selectforeground=[("readonly", TEXTO)], **foco)
        self.option_add("*TCombobox*Listbox.font", (FONTE, 10))
        self.option_add("*TCombobox*Listbox.selectBackground", ACENTO)

        # Caixa de seleção com o quadradinho verde quando marcada
        estilo.configure("TCheckbutton", indicatorbackground=CARTAO, indicatorforeground="white",
                         upperbordercolor="#9ca3af", lowerbordercolor="#9ca3af",
                         indicatorsize=self.px(15), indicatormargin=(0, 0, self.px(8), 0),
                         focuscolor=CARTAO)
        estilo.map("TCheckbutton", background=[("active", CARTAO)],
                   indicatorbackground=[("selected", ACENTO)])

        # Botões cheios: verde para receita (e "Salvar"), vermelho para despesa
        for nome, cor, cor_escura in [("Receita", ACENTO, ACENTO_ESCURO),
                                      ("Despesa", PERIGO, PERIGO_ESCURO)]:
            estilo.configure(f"{nome}.TButton", background=cor, foreground="white",
                             bordercolor=cor, lightcolor=cor, darkcolor=cor, focuscolor=cor,
                             font=(FONTE, 10, "bold"), padding=self.px(10))
            estilo.map(f"{nome}.TButton",
                       background=[("active", cor_escura)], bordercolor=[("active", cor_escura)],
                       lightcolor=[("active", cor_escura)], darkcolor=[("active", cor_escura)])

        # Botão branco com borda (ações secundárias)
        estilo.configure("Secundario.TButton", background=CARTAO, foreground=TEXTO,
                         bordercolor=BORDA, lightcolor=CARTAO, darkcolor=CARTAO,
                         focuscolor=CARTAO, padding=(self.px(12), self.px(6)))
        estilo.map("Secundario.TButton", background=[("active", FUNDO)])

        # Botão de remover (vermelho discreto)
        estilo.configure("Perigo.TButton", background=CARTAO, foreground=PERIGO,
                         bordercolor=BORDA, lightcolor=CARTAO, darkcolor=CARTAO,
                         focuscolor=CARTAO, padding=(self.px(12), self.px(6)))
        estilo.map("Perigo.TButton", background=[("active", "#fef2f2")],
                   bordercolor=[("active", PERIGO)])

        # Botão que parece um link
        estilo.configure("Link.TButton", background=CARTAO, foreground=ACENTO_ESCURO,
                         bordercolor=CARTAO, lightcolor=CARTAO, darkcolor=CARTAO,
                         focuscolor=CARTAO, padding=0, font=(FONTE, 9, "underline"))
        estilo.map("Link.TButton", background=[("active", CARTAO)], foreground=[("active", ACENTO)])

        # Abas sem bordas, com a aba ativa destacada em verde claro
        estilo.configure("TNotebook", background=CARTAO, borderwidth=0, bordercolor=CARTAO,
                         lightcolor=CARTAO, darkcolor=CARTAO, tabmargins=0)
        estilo.configure("TNotebook.Tab", background=CARTAO, foreground=TEXTO_SUAVE,
                         bordercolor=CARTAO, lightcolor=CARTAO, font=(FONTE, 10, "bold"),
                         padding=(self.px(16), self.px(8)))
        estilo.map("TNotebook.Tab",
                   background=[("selected", ACENTO_CLARO), ("active", FUNDO)],
                   foreground=[("selected", ACENTO_ESCURO)],
                   lightcolor=[("selected", ACENTO_CLARO)], expand=[("selected", 0)])

        # Tabelas: linhas mais altas, sem bordas, cabeçalho cinza
        estilo.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        estilo.configure("Treeview", background=CARTAO, fieldbackground=CARTAO,
                         foreground=TEXTO, rowheight=self.px(34), borderwidth=0)
        estilo.map("Treeview", background=[("selected", ACENTO_CLARO)],
                   foreground=[("selected", ACENTO_ESCURO)])
        estilo.configure("Treeview.Heading", background=FUNDO, foreground=TEXTO_SUAVE,
                         font=(FONTE, 9, "bold"), relief="flat", bordercolor=FUNDO,
                         lightcolor=FUNDO, darkcolor=FUNDO, padding=(self.px(8), self.px(8)))
        estilo.map("Treeview.Heading", background=[("active", BORDA)])

        # Barra de rolagem fina, sem as setinhas
        estilo.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        estilo.configure("Vertical.TScrollbar", background="#d1d5db", troughcolor=CARTAO,
                         bordercolor=CARTAO, lightcolor="#d1d5db", darkcolor="#d1d5db",
                         gripcount=0, arrowsize=self.px(8))
        estilo.map("Vertical.TScrollbar", background=[("active", "#9ca3af")])

    def criar_cartao(self, pai):
        """Um retângulo branco com borda fina, usado como 'cartão'."""
        return tk.Frame(pai, bg=CARTAO, highlightthickness=1,
                        highlightbackground=BORDA, highlightcolor=BORDA)

    def criar_tabela(self, pai, colunas):
        """Tabela no estilo do app. 'colunas' = [(id, título, largura, alinhamento), ...]"""
        tabela = ttk.Treeview(pai, columns=[c[0] for c in colunas], show="headings")
        for coluna, titulo, largura, alinhamento in colunas:
            tabela.heading(coluna, text=titulo, anchor=alinhamento)
            tabela.column(coluna, width=self.px(largura), anchor=alinhamento)
        tabela.tag_configure("listra", background=LISTRA)
        return tabela

    def criar_rolagem(self, pai, tabela):
        """Barra de rolagem que só aparece quando a tabela não cabe na tela."""
        barra = ttk.Scrollbar(pai, orient="vertical", command=tabela.yview)

        def rolar(inicio, fim):
            if float(inicio) <= 0 and float(fim) >= 1:
                barra.pack_forget()
            else:
                barra.pack(side="right", fill="y", before=tabela)
            barra.set(inicio, fim)

        tabela.configure(yscrollcommand=rolar)

    # ---------------- Cabeçalho, seletor de mês e indicadores ----------------

    def criar_cabecalho(self):
        cabecalho = tk.Frame(self, bg=FUNDO)
        cabecalho.pack(fill="x", padx=self.px(24), pady=(self.px(20), 0))

        titulos = tk.Frame(cabecalho, bg=FUNDO)
        titulos.pack(side="left")
        tk.Label(titulos, text="Controle de Gastos", bg=FUNDO, fg=TEXTO,
                 font=(FONTE, 20, "bold")).pack(anchor="w")
        tk.Label(titulos, text="Registre o que entra e o que sai e acompanhe o seu saldo.",
                 bg=FUNDO, fg=TEXTO_SUAVE, font=(FONTE, 10)).pack(anchor="w")

        # Seletor de mês:  ‹  Outubro de 2026  ›   [Todos os meses]
        navegador = tk.Frame(cabecalho, bg=FUNDO)
        navegador.pack(side="right")
        ttk.Button(navegador, text="‹", width=3, style="Secundario.TButton", cursor="hand2",
                   command=lambda: self.mudar_mes(-1)).pack(side="left")
        self.label_mes = tk.Label(navegador, bg=FUNDO, fg=TEXTO, font=(FONTE, 12, "bold"), width=17)
        self.label_mes.pack(side="left", padx=self.px(6))
        ttk.Button(navegador, text="›", width=3, style="Secundario.TButton", cursor="hand2",
                   command=lambda: self.mudar_mes(1)).pack(side="left")
        self.botao_todos = ttk.Button(navegador, width=15, style="Secundario.TButton",
                                      cursor="hand2", command=self.alternar_todos)
        self.botao_todos.pack(side="left", padx=(self.px(12), 0))

        indicadores = tk.Frame(self, bg=FUNDO)
        indicadores.pack(fill="x", padx=self.px(24), pady=self.px(16))
        self.titulo_saldo, self.label_saldo = self.criar_indicador(indicadores, "Saldo atual", 0, "#3b82f6")
        self.titulo_receitas, self.label_receitas = self.criar_indicador(indicadores, "", 1, ACENTO)
        self.titulo_despesas, self.label_despesas = self.criar_indicador(indicadores, "", 2, PERIGO)

    def criar_indicador(self, pai, titulo, coluna, cor):
        pai.columnconfigure(coluna, weight=1, uniform="indicadores")
        cartao = self.criar_cartao(pai)
        espaco = (0, 0) if coluna == 2 else (0, self.px(14))
        cartao.grid(row=0, column=coluna, sticky="ew", padx=espaco)

        # Faixa colorida na lateral esquerda do cartão
        tk.Frame(cartao, bg=cor, width=self.px(4)).pack(side="left", fill="y")
        label_titulo = ttk.Label(cartao, text=titulo, style="Suave.TLabel")
        label_titulo.pack(anchor="w", padx=self.px(16), pady=(self.px(12), 0))
        valor = ttk.Label(cartao, text=formatar_reais(0), style="Indicador.TLabel")
        valor.pack(anchor="w", padx=self.px(16), pady=(0, self.px(12)))
        return label_titulo, valor

    def mudar_mes(self, quantidade):
        self.mes = somar_meses(self.mes or mes_atual(), quantidade)
        self.atualizar_tudo()

    def alternar_todos(self):
        self.mes = None if self.mes else mes_atual()
        self.atualizar_tudo()

    # ---------------- Formulário (adicionar e editar) ----------------

    def criar_conteudo(self):
        conteudo = tk.Frame(self, bg=FUNDO)
        conteudo.pack(fill="both", expand=True, padx=self.px(24), pady=(0, self.px(24)))
        conteudo.columnconfigure(1, weight=1)
        conteudo.rowconfigure(0, weight=1)

        cartao_form = self.criar_cartao(conteudo)
        cartao_form.grid(row=0, column=0, sticky="ns", padx=(0, self.px(14)))
        self.criar_formulario(cartao_form)

        cartao_abas = self.criar_cartao(conteudo)
        cartao_abas.grid(row=0, column=1, sticky="nsew")
        self.criar_abas(cartao_abas)

    def criar_formulario(self, cartao):
        frame = ttk.Frame(cartao, padding=self.px(20))
        frame.pack(fill="both", expand=True)

        self.var_descricao = tk.StringVar()
        self.var_valor = tk.StringVar()
        self.var_categoria = tk.StringVar()
        self.var_data = tk.StringVar(value=date.today().strftime("%d/%m/%Y"))
        self.var_repetir = tk.BooleanVar()

        self.label_titulo_form = ttk.Label(frame, text="Novo lançamento", style="TituloCartao.TLabel")
        self.label_titulo_form.pack(anchor="w", pady=(0, self.px(12)))

        # Chave Despesa / Receita: dois "botões" lado a lado dentro de uma faixa cinza
        seletor = tk.Frame(frame, bg=FUNDO, padx=self.px(3), pady=self.px(3))
        seletor.pack(fill="x", pady=(0, self.px(12)))
        self.botoes_tipo = {}
        for tipo, texto in [("despesa", "Despesa"), ("receita", "Receita")]:
            botao = tk.Label(seletor, text=texto, font=(FONTE, 10, "bold"),
                             pady=self.px(6), cursor="hand2")
            botao.pack(side="left", fill="x", expand=True)
            botao.bind("<Button-1>", lambda evento, t=tipo: self.mudar_tipo(t))
            self.botoes_tipo[tipo] = botao

        def campo(rotulo, widget):
            ttk.Label(frame, text=rotulo, style="Suave.TLabel").pack(anchor="w")
            widget.pack(fill="x", pady=(self.px(2), self.px(10)))
            return widget

        self.entrada_descricao = campo("Descrição",
                                       ttk.Entry(frame, textvariable=self.var_descricao, width=28))
        campo("Valor (R$)", ttk.Entry(frame, textvariable=self.var_valor))
        self.combo_categoria = campo("Categoria", ttk.Combobox(
            frame, textvariable=self.var_categoria, state="readonly"))
        campo("Data (DD/MM/AAAA)", ttk.Entry(frame, textvariable=self.var_data))
        self.entrada_descricao.focus()

        self.check_repetir = ttk.Checkbutton(frame, text="Repetir todo mês", variable=self.var_repetir,
                                             cursor="hand2")
        self.check_repetir.pack(anchor="w", pady=(0, self.px(12)))

        self.botao_salvar = ttk.Button(frame, cursor="hand2", command=self.salvar_formulario)
        self.botao_salvar.pack(fill="x")
        # Só aparece durante a edição
        self.botao_cancelar = ttk.Button(frame, text="Cancelar edição", style="Secundario.TButton",
                                         cursor="hand2", command=self.limpar_formulario)

        ttk.Button(frame, text="Gerenciar categorias", style="Link.TButton", cursor="hand2",
                   command=self.abrir_categorias).pack(side="bottom", anchor="w")
        ttk.Button(frame, text="Ver lançamentos recorrentes", style="Link.TButton", cursor="hand2",
                   command=self.abrir_recorrentes).pack(side="bottom", anchor="w", pady=(0, self.px(6)))

        # Nos campos do formulário, Enter salva e Esc cancela a edição
        for filho in frame.winfo_children():
            if isinstance(filho, (ttk.Entry, ttk.Checkbutton)):
                filho.bind("<Return>", lambda evento: self.salvar_formulario())
                filho.bind("<Escape>", lambda evento: self.limpar_formulario())

    def mudar_tipo(self, tipo, categoria=None):
        """Troca o formulário entre despesa e receita (cores, categorias e botão)."""
        self.tipo = tipo
        for t, botao in self.botoes_tipo.items():
            if t == tipo:
                botao.config(bg=CARTAO, fg=COR_TIPO[t])
            else:
                botao.config(bg=FUNDO, fg=TEXTO_SUAVE)

        categorias = categorias_do_tipo(self.dados, tipo)
        self.combo_categoria.config(values=categorias)
        self.var_categoria.set(categoria if categoria in categorias else categorias[0])
        self.atualizar_botao_salvar()

    def atualizar_botao_salvar(self):
        texto = "Salvar alterações" if self.editando is not None else f"+  Adicionar {self.tipo}"
        self.botao_salvar.config(text=texto, style=f"{self.tipo.capitalize()}.TButton")

    def salvar_formulario(self):
        try:
            valor = validar_valor(self.var_valor.get())
            data = validar_data(self.var_data.get())
        except ValueError as erro:
            messagebox.showerror("Dado inválido", str(erro))
            return

        lancamento = {
            "tipo": self.tipo,
            "descricao": self.var_descricao.get().strip() or "Sem descrição",
            "valor": valor,
            "categoria": self.var_categoria.get(),
            "data": data,
        }
        if self.editando is None:
            self.dados["lancamentos"].append(lancamento)
            if self.var_repetir.get():
                criar_recorrente(self.dados, lancamento)
        else:
            antigo = self.dados["lancamentos"][self.editando]
            if antigo.get("recorrente"):
                lancamento["recorrente"] = antigo["recorrente"]
            self.dados["lancamentos"][self.editando] = lancamento

            recorrente = recorrente_do_lancamento(self.dados, lancamento)
            campos = ("tipo", "descricao", "valor", "categoria", "data")
            mudou = any(antigo[c] != lancamento[c] for c in campos)
            if recorrente and mudou and messagebox.askyesno(
                    "Lançamento recorrente",
                    "Este lançamento se repete todo mês.\n\n"
                    "Aplicar as mudanças também aos próximos meses?"):
                atualizar_recorrente(recorrente, lancamento)

        # Mostra o mês do lançamento salvo, para a pessoa ver onde ele foi parar
        if self.mes is not None:
            self.mes = data[:7]
        self.limpar_formulario()
        self.salvar()

    def limpar_formulario(self):
        """Volta o formulário para o modo 'adicionar', com os campos vazios."""
        self.editando = None
        self.var_descricao.set("")
        self.var_valor.set("")
        self.var_data.set(date.today().strftime("%d/%m/%Y"))
        self.var_repetir.set(False)
        self.label_titulo_form.config(text="Novo lançamento")
        self.botao_cancelar.pack_forget()
        self.check_repetir.pack(anchor="w", pady=(0, self.px(12)), before=self.botao_salvar)
        self.atualizar_botao_salvar()
        self.entrada_descricao.focus()

    def editar_selecionado(self, evento=None):
        """Carrega o lançamento da linha clicada no formulário para editar."""
        linha = self.tabela.identify_row(evento.y) if evento else ""
        selecionado = linha or (self.tabela.selection() or [None])[0]
        if selecionado is None:
            return

        self.editando = int(selecionado)
        l = self.dados["lancamentos"][self.editando]
        self.mudar_tipo(l["tipo"], categoria=l["categoria"])
        self.var_descricao.set(l["descricao"])
        self.var_valor.set(formatar_numero(l["valor"]))
        self.var_data.set(formatar_data(l["data"]))

        self.label_titulo_form.config(text="Editar lançamento")
        self.check_repetir.pack_forget()
        self.botao_cancelar.pack(fill="x", pady=(self.px(8), 0), after=self.botao_salvar)
        self.atualizar_botao_salvar()
        self.entrada_descricao.focus()

    # ---------------- Abas ----------------

    def criar_abas(self, cartao):
        abas = ttk.Notebook(cartao)
        abas.pack(fill="both", expand=True, padx=self.px(12), pady=self.px(12))
        self.criar_aba_lancamentos(abas)
        self.criar_aba_categorias(abas)
        self.criar_aba_meses(abas)

    def criar_aba_lancamentos(self, abas):
        aba = ttk.Frame(abas, padding=(0, self.px(10), 0, 0))
        abas.add(aba, text="Lançamentos")

        # Barra de cima: busca e exportar
        barra = ttk.Frame(aba)
        barra.pack(side="top", fill="x", pady=(0, self.px(10)))
        ttk.Label(barra, text="Buscar", style="Suave.TLabel").pack(side="left", padx=(0, self.px(8)))
        self.var_busca = tk.StringVar()
        self.var_busca.trace_add("write", lambda *args: self.atualizar_lista())
        ttk.Entry(barra, textvariable=self.var_busca, width=30).pack(side="left")
        ttk.Button(barra, text="Exportar para Excel", style="Secundario.TButton", cursor="hand2",
                   command=self.exportar).pack(side="right")

        rodape = ttk.Frame(aba)
        rodape.pack(side="bottom", fill="x", pady=(self.px(10), 0))
        ttk.Label(rodape, text="Duplo clique para editar  ·  Delete para remover",
                  style="Suave.TLabel").pack(side="left")
        ttk.Button(rodape, text="Remover selecionado", style="Perigo.TButton",
                   cursor="hand2", command=self.remover_lancamento).pack(side="right")

        self.tabela = self.criar_tabela(aba, [
            ("data", "DATA", 100, "center"),
            ("descricao", "DESCRIÇÃO", 220, "w"),
            ("categoria", "CATEGORIA", 120, "w"),
            ("valor", "VALOR", 130, "e"),
        ])
        self.tabela.tag_configure("receita", foreground=ACENTO_ESCURO)
        self.tabela.tag_configure("futuro", foreground=TEXTO_SUAVE)
        self.criar_rolagem(aba, self.tabela)
        self.tabela.pack(side="left", fill="both", expand=True)
        self.tabela.bind("<Double-1>", self.editar_selecionado)
        self.tabela.bind("<Delete>", lambda evento: self.remover_lancamento())

        # Mensagem que aparece no meio da tabela quando ela está vazia
        self.label_vazio = ttk.Label(self.tabela, style="Suave.TLabel", background=CARTAO)

    def criar_aba_categorias(self, abas):
        aba = ttk.Frame(abas, padding=(0, self.px(10), 0, 0))
        abas.add(aba, text="Despesas por categoria")

        barra = ttk.Frame(aba)
        barra.pack(fill="x")
        self.label_info_categorias = ttk.Label(barra, style="Suave.TLabel")
        self.label_info_categorias.pack(side="left")
        ttk.Button(barra, text="Definir orçamentos", style="Secundario.TButton", cursor="hand2",
                   command=self.abrir_orcamentos).pack(side="right")

        self.canvas_categorias = tk.Canvas(aba, background=CARTAO, highlightthickness=0)
        self.canvas_categorias.pack(fill="both", expand=True)
        # Redesenha o gráfico quando a janela muda de tamanho
        self.canvas_categorias.bind("<Configure>", lambda evento: self.desenhar_categorias())

    def criar_aba_meses(self, abas):
        aba = ttk.Frame(abas, padding=(0, self.px(10), 0, 0))
        abas.add(aba, text="Por mês")

        self.canvas_meses = tk.Canvas(aba, background=CARTAO, highlightthickness=0,
                                      height=self.px(190))
        self.canvas_meses.pack(fill="x")
        self.canvas_meses.bind("<Configure>", lambda evento: self.desenhar_evolucao())

        ttk.Label(aba, text="Duplo clique num mês para ver os lançamentos dele.",
                  style="Suave.TLabel").pack(side="bottom", anchor="w", pady=(self.px(8), 0))
        self.tabela_mes = self.criar_tabela(aba, [
            ("mes", "MÊS", 120, "center"),
            ("receitas", "RECEITAS", 120, "e"),
            ("despesas", "DESPESAS", 120, "e"),
            ("saldo", "SALDO", 120, "e"),
        ])
        self.tabela_mes.tag_configure("negativo", foreground=PERIGO)
        self.criar_rolagem(aba, self.tabela_mes)
        self.tabela_mes.pack(side="left", fill="both", expand=True, pady=(self.px(8), 0))
        self.tabela_mes.bind("<Double-1>", self.abrir_mes_da_tabela)

    # ---------------- Atualização das telas ----------------

    def atualizar_tudo(self):
        self.atualizar_cabecalho()
        self.atualizar_lista()
        self.desenhar_categorias()
        self.desenhar_evolucao()
        self.atualizar_tabela_meses()

    def atualizar_cabecalho(self):
        self.label_mes.config(text=formatar_mes(self.mes) if self.mes else "Todos os meses")
        self.botao_todos.config(text="Voltar ao mês atual" if self.mes is None else "Todos os meses")

        totais = totais_por_tipo(self.lancamentos_do_mes())
        periodo = "no mês" if self.mes else "(todo o período)"
        self.titulo_receitas.config(text=f"Receitas {periodo}")
        self.titulo_despesas.config(text=f"Despesas {periodo}")
        self.label_receitas.config(text=formatar_reais(totais["receita"]))
        self.label_despesas.config(text=formatar_reais(totais["despesa"]))

        # O saldo atual não conta o que está agendado para depois de hoje
        saldo = calcular_saldo(self.dados["lancamentos"], ate=date.today())
        previsto = calcular_saldo(self.dados["lancamentos"])
        self.label_saldo.config(text=formatar_saldo(saldo), foreground=PERIGO if saldo < 0 else TEXTO)
        titulo = "Saldo atual"
        if previsto != saldo:
            titulo += f"  ·  com os agendados: {formatar_saldo(previsto)}"
        self.titulo_saldo.config(text=titulo)

    def atualizar_lista(self):
        self.tabela.delete(*self.tabela.get_children())

        # O "iid" de cada linha é a posição do lançamento na lista, para saber qual editar/remover
        itens = self.lancamentos_visiveis()
        for linha, (indice, l) in enumerate(itens):
            sinal = "+" if l["tipo"] == "receita" else "−"
            descricao = f"↻  {l['descricao']}" if l.get("recorrente") else l["descricao"]
            cor = l["tipo"]
            if eh_futuro(l):
                descricao += "  (agendado)"
                cor = "futuro"  # cinza, para não parecer que já aconteceu
            tags = [cor] + (["listra"] if linha % 2 else [])
            self.tabela.insert("", "end", iid=str(indice), tags=tags, values=(
                formatar_data(l["data"]), descricao, l["categoria"],
                f"{sinal} {formatar_reais(l['valor'])}"))

        if itens:
            self.label_vazio.place_forget()
        else:
            busca = self.var_busca.get().strip()
            if busca:
                texto = f"Nada encontrado para \"{busca}\"."
            elif self.mes:
                texto = "Nenhum lançamento neste mês.\nUse o formulário ao lado para adicionar."
            else:
                texto = "Nenhum lançamento ainda.\nUse o formulário ao lado para adicionar."
            self.label_vazio.config(text=texto, justify="center")
            self.label_vazio.place(relx=0.5, rely=0.4, anchor="center")

    def desenhar_categorias(self):
        c = self.canvas_categorias
        c.delete("all")
        largura = c.winfo_width()
        margem = self.px(4)

        totais = totais_por_categoria(self.lancamentos_do_mes(), "despesa")
        # Orçamentos são mensais: só fazem sentido quando um mês foi escolhido
        orcamentos = self.dados["orcamentos"] if self.mes else {}
        if self.mes:
            self.label_info_categorias.config(text=f"Despesas de {formatar_mes(self.mes)}")
        else:
            self.label_info_categorias.config(
                text="Despesas de todo o período (escolha um mês para comparar com o orçamento)")

        categorias = sorted(set(totais) | set(orcamentos), key=lambda cat: totais.get(cat, 0),
                            reverse=True)
        if not categorias:
            c.create_text(largura / 2, self.px(60), text="Nenhuma despesa neste período.",
                          fill=TEXTO_SUAVE, font=(FONTE, 10))
            return

        lista_categorias = categorias_do_tipo(self.dados, "despesa")
        total_geral = sum(totais.values()) or 1
        maior = max(totais.values(), default=0) or 1

        # Barras arredondadas: linhas grossas com pontas redondas.
        # Atrás de cada barra fica um "trilho" cinza do tamanho total.
        espessura = self.px(12)
        inicio = margem + espessura / 2
        fim_maximo = largura - margem - espessura / 2

        y = self.px(26)
        for categoria in categorias:
            gasto = totais.get(categoria, 0)
            limite = orcamentos.get(categoria)
            situacao = situacao_orcamento(gasto, limite)

            if situacao == "sem":
                # Sem orçamento: barra proporcional à maior categoria
                proporcao = gasto / maior
                cor = cor_da_categoria(categoria, lista_categorias)
                texto, cor_texto = f"{formatar_reais(gasto)}  ·  {gasto / total_geral * 100:.1f}%", TEXTO_SUAVE
            else:
                # Com orçamento: barra mostra quanto do limite já foi usado
                proporcao = min(gasto / limite, 1)
                cor = {"ok": cor_da_categoria(categoria, lista_categorias), "alerta": ALERTA, "estourado": PERIGO}[situacao]
                texto = f"{formatar_reais(gasto)} de {formatar_reais(limite)}"
                cor_texto = TEXTO_SUAVE
                if situacao == "alerta":
                    texto, cor_texto = f"Quase no limite  ·  {texto}", ALERTA
                elif situacao == "estourado":
                    texto = f"Passou {formatar_reais(gasto - limite)}  ·  {texto}"
                    cor_texto = PERIGO

            c.create_text(margem, y, text=categoria, anchor="w", fill=TEXTO,
                          font=(FONTE, 10, "bold"))
            c.create_text(largura - margem, y, anchor="e", fill=cor_texto, font=(FONTE, 10),
                          text=texto)

            y_barra = y + self.px(20)
            c.create_line(inicio, y_barra, fim_maximo, y_barra, width=espessura,
                          fill=FUNDO, capstyle="round")
            if proporcao > 0:
                fim = inicio + (fim_maximo - inicio) * proporcao
                c.create_line(inicio, y_barra, max(fim, inicio + 1), y_barra, width=espessura,
                              fill=cor, capstyle="round")
            y += self.px(50)

    def desenhar_evolucao(self):
        """Gráfico de barras: receitas x despesas dos últimos 6 meses."""
        c = self.canvas_meses
        c.delete("all")
        largura, altura = c.winfo_width(), c.winfo_height()
        if largura < 50:
            return  # janela ainda não foi desenhada

        totais = totais_por_mes(self.dados["lancamentos"])
        fim = self.mes or mes_atual()
        meses = [somar_meses(fim, i - 5) for i in range(6)]
        maior = max([totais.get(m, {}).get(t, 0) for m in meses for t in TIPOS] + [1])

        margem = self.px(8)
        topo, base = self.px(40), altura - self.px(26)

        # Legenda
        x = margem
        for tipo, texto in [("receita", "Receitas"), ("despesa", "Despesas")]:
            c.create_rectangle(x, self.px(10), x + self.px(10), self.px(20),
                               fill=COR_TIPO[tipo], outline="")
            c.create_text(x + self.px(16), self.px(15), text=texto, anchor="w",
                          fill=TEXTO_SUAVE, font=(FONTE, 9))
            x += self.px(90)

        c.create_line(margem, base, largura - margem, base, fill=BORDA)
        fatia = (largura - 2 * margem) / len(meses)
        largura_barra = min(self.px(28), fatia / 4)
        for i, mes in enumerate(meses):
            centro = margem + fatia * (i + 0.5)
            for j, tipo in enumerate(("receita", "despesa")):
                valor = totais.get(mes, {}).get(tipo, 0)
                if not valor:
                    continue
                altura_barra = max((base - topo) * valor / maior, 2)
                x0 = centro - largura_barra - self.px(2) if j == 0 else centro + self.px(2)
                c.create_rectangle(x0, base - altura_barra, x0 + largura_barra, base,
                                   fill=COR_TIPO[tipo], outline="")
            destaque = mes == fim
            c.create_text(centro, base + self.px(13), text=formatar_mes_curto(mes),
                          fill=TEXTO if destaque else TEXTO_SUAVE,
                          font=(FONTE, 9, "bold" if destaque else "normal"))

    def atualizar_tabela_meses(self):
        self.tabela_mes.delete(*self.tabela_mes.get_children())
        totais = totais_por_mes(self.dados["lancamentos"])

        for linha, mes in enumerate(sorted(totais, reverse=True)):
            receitas, despesas = totais[mes]["receita"], totais[mes]["despesa"]
            saldo = receitas - despesas
            tags = (["negativo"] if saldo < 0 else []) + (["listra"] if linha % 2 else [])
            ano, numero_mes = mes.split("-")
            self.tabela_mes.insert("", "end", iid=mes, tags=tags, values=(
                f"{numero_mes}/{ano}", formatar_reais(receitas),
                formatar_reais(despesas), formatar_saldo(saldo)))

        if self.mes in totais:
            self.tabela_mes.selection_set(self.mes)

    def abrir_mes_da_tabela(self, evento):
        mes = self.tabela_mes.identify_row(evento.y)
        if mes:
            self.mes = mes
            self.atualizar_tudo()

    # ---------------- Remover e exportar ----------------

    def remover_lancamento(self):
        selecionado = self.tabela.selection()
        if not selecionado:
            messagebox.showinfo("Remover", "Selecione um lançamento na tabela primeiro.")
            return

        indice = int(selecionado[0])
        l = self.dados["lancamentos"][indice]
        if messagebox.askyesno("Remover", f"Remover \"{l['descricao']}\" ({formatar_reais(l['valor'])})?"):
            self.dados["lancamentos"].pop(indice)
            recorrente = recorrente_do_lancamento(self.dados, l)
            if recorrente and messagebox.askyesno(
                    "Lançamento recorrente",
                    "Este lançamento se repete todo mês.\n\nParar de criá-lo nos próximos meses?"):
                parar_recorrente(self.dados, recorrente)
            self.limpar_formulario()  # as posições mudaram: uma edição aberta ficaria errada
            self.salvar()

    def exportar(self):
        """Exporta para CSV exatamente o que está na tabela (mês e busca atuais)."""
        lancamentos = [l for _, l in self.lancamentos_visiveis()]
        if not lancamentos:
            messagebox.showinfo("Exportar", "Não há lançamentos na tabela para exportar.")
            return

        caminho = filedialog.asksaveasfilename(
            parent=self, title="Exportar para Excel (CSV)", defaultextension=".csv",
            initialfile=f"lancamentos-{self.mes or 'todos'}.csv",
            filetypes=[("Planilha CSV", "*.csv")])
        if not caminho:
            return
        try:
            exportar_csv(lancamentos, caminho)
        except OSError as erro:
            messagebox.showerror("Exportar", "Não foi possível salvar o arquivo. "
                                 f"Ele está aberto no Excel?\n\n{erro}")
            return
        messagebox.showinfo("Exportar", f"{len(lancamentos)} lançamento(s) exportado(s) para:\n"
                                        f"{caminho}\n\nO arquivo abre direto no Excel.")

    # ---------------- Janelas extras: orçamentos e recorrentes ----------------

    def criar_dialogo(self, titulo):
        """Janela pequena por cima da principal, que bloqueia a principal até fechar."""
        janela = tk.Toplevel(self, bg=CARTAO)
        janela.title(titulo)
        janela.resizable(False, False)
        janela.transient(self)
        janela.bind("<Escape>", lambda evento: janela.destroy())
        frame = ttk.Frame(janela, padding=self.px(22))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=titulo, style="TituloCartao.TLabel").pack(anchor="w")
        return janela, frame

    def mostrar_dialogo(self, janela):
        """Centraliza o diálogo sobre a janela principal e espera ele fechar."""
        janela.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - janela.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - janela.winfo_reqheight()) // 3
        janela.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        janela.grab_set()
        janela.focus_set()

    def abrir_orcamentos(self):
        janela, frame = self.criar_dialogo("Orçamentos mensais")
        ttk.Label(frame, style="Suave.TLabel", justify="left",
                  text="Quanto você quer gastar, no máximo, por mês em cada categoria.\n"
                       "Deixe em branco (ou 0) para não ter limite.").pack(anchor="w", pady=(self.px(2), self.px(14)))

        grade = ttk.Frame(frame)
        grade.pack(fill="x")
        variaveis = {}
        for linha, categoria in enumerate(categorias_do_tipo(self.dados, "despesa")):
            ttk.Label(grade, text=categoria).grid(row=linha, column=0, sticky="w", pady=self.px(4))
            atual = self.dados["orcamentos"].get(categoria)
            variaveis[categoria] = tk.StringVar(value=formatar_numero(atual) if atual else "")
            ttk.Label(grade, text="R$", style="Suave.TLabel").grid(row=linha, column=1, padx=(self.px(24), self.px(6)))
            ttk.Entry(grade, textvariable=variaveis[categoria], width=12, justify="right").grid(
                row=linha, column=2, sticky="e", pady=self.px(4))

        def salvar():
            novos = {}
            for categoria, variavel in variaveis.items():
                if variavel.get().strip():
                    try:
                        valor = validar_valor(variavel.get(), aceitar_zero=True)
                    except ValueError as erro:
                        messagebox.showerror("Valor inválido", f"{categoria}: {erro}", parent=janela)
                        return
                    if valor:
                        novos[categoria] = valor
            self.dados["orcamentos"] = novos
            janela.destroy()
            self.salvar()

        botoes = ttk.Frame(frame)
        botoes.pack(fill="x", pady=(self.px(18), 0))
        ttk.Button(botoes, text="Salvar", style="Receita.TButton", cursor="hand2",
                   command=salvar).pack(side="right")
        ttk.Button(botoes, text="Cancelar", style="Secundario.TButton", cursor="hand2",
                   command=janela.destroy).pack(side="right", padx=(0, self.px(8)))
        janela.bind("<Return>", lambda evento: salvar())
        self.mostrar_dialogo(janela)

    def abrir_recorrentes(self):
        janela, frame = self.criar_dialogo("Lançamentos recorrentes")
        ttk.Label(frame, style="Suave.TLabel", justify="left",
                  text="Estes lançamentos são criados sozinhos todo mês, no dia indicado.\n"
                       "Para criar um, marque \"Repetir todo mês\" ao adicionar um lançamento.").pack(
            anchor="w", pady=(self.px(2), self.px(14)))

        area = ttk.Frame(frame, height=self.px(220), width=self.px(560))
        area.pack(fill="both")
        area.pack_propagate(False)
        tabela = self.criar_tabela(area, [
            ("descricao", "DESCRIÇÃO", 190, "w"),
            ("categoria", "CATEGORIA", 120, "w"),
            ("valor", "VALOR", 130, "e"),
            ("dia", "DIA", 60, "center"),
        ])
        tabela.tag_configure("receita", foreground=ACENTO_ESCURO)
        tabela.pack(fill="both", expand=True)
        vazio = ttk.Label(tabela, text="Nenhum lançamento recorrente.", style="Suave.TLabel",
                          background=CARTAO)

        def preencher():
            tabela.delete(*tabela.get_children())
            for indice, r in enumerate(self.dados["recorrentes"]):
                sinal = "+" if r["tipo"] == "receita" else "−"
                tabela.insert("", "end", iid=str(indice), tags=[r["tipo"]], values=(
                    r["descricao"], r["categoria"], f"{sinal} {formatar_reais(r['valor'])}",
                    r["dia"]))
            if self.dados["recorrentes"]:
                vazio.place_forget()
            else:
                vazio.place(relx=0.5, rely=0.45, anchor="center")

        def parar():
            selecionado = tabela.selection()
            if not selecionado:
                messagebox.showinfo("Recorrentes", "Selecione um lançamento primeiro.", parent=janela)
                return
            r = self.dados["recorrentes"][int(selecionado[0])]
            if messagebox.askyesno("Parar de repetir",
                                   f"Parar de criar \"{r['descricao']}\" todo mês?\n\n"
                                   "Os lançamentos que já foram criados continuam na lista.",
                                   parent=janela):
                parar_recorrente(self.dados, r)
                self.salvar()
                preencher()

        botoes = ttk.Frame(frame)
        botoes.pack(fill="x", pady=(self.px(16), 0))
        ttk.Button(botoes, text="Fechar", style="Secundario.TButton", cursor="hand2",
                   command=janela.destroy).pack(side="right")
        ttk.Button(botoes, text="Parar de repetir", style="Perigo.TButton", cursor="hand2",
                   command=parar).pack(side="right", padx=(0, self.px(8)))

        preencher()
        self.mostrar_dialogo(janela)

    def abrir_categorias(self):
        janela, frame = self.criar_dialogo("Categorias")
        ttk.Label(frame, style="Suave.TLabel", justify="left",
                  text="Crie as suas próprias categorias ou remova as que não usa.\n"
                       "Categorias que já têm lançamentos não podem ser removidas.").pack(
            anchor="w", pady=(self.px(2), self.px(14)))

        colunas = ttk.Frame(frame)
        colunas.pack(fill="both")

        def coluna(tipo, titulo, posicao):
            area = ttk.Frame(colunas)
            area.grid(row=0, column=posicao, sticky="nsew",
                      padx=(0, self.px(18)) if posicao == 0 else 0)
            ttk.Label(area, text=titulo, font=(FONTE, 10, "bold"),
                      foreground=COR_TIPO[tipo]).pack(anchor="w", pady=(0, self.px(6)))

            caixa = ttk.Frame(area, height=self.px(280), width=self.px(230))
            caixa.pack(fill="both")
            caixa.pack_propagate(False)
            tabela = self.criar_tabela(caixa, [("nome", "NOME", 200, "w")])
            self.criar_rolagem(caixa, tabela)
            tabela.pack(side="left", fill="both", expand=True)

            def preencher():
                tabela.delete(*tabela.get_children())
                # O "iid" de cada linha é a posição da categoria na lista
                for linha, nome in enumerate(categorias_do_tipo(self.dados, tipo)):
                    tabela.insert("", "end", iid=str(linha), values=(nome,),
                                  tags=["listra"] if linha % 2 else [])

            var_nome = tk.StringVar()

            def adicionar():
                try:
                    nome = adicionar_categoria(self.dados, tipo, var_nome.get())
                except ValueError as erro:
                    messagebox.showerror("Categorias", str(erro), parent=janela)
                    return
                var_nome.set("")
                self.salvar_categorias(tipo)
                preencher()
                lista = categorias_do_tipo(self.dados, tipo)
                if nome in lista:
                    linha = str(lista.index(nome))
                    tabela.selection_set(linha)
                    tabela.see(linha)

            def remover():
                selecionado = tabela.selection()
                if not selecionado:
                    messagebox.showinfo("Categorias", "Selecione uma categoria primeiro.", parent=janela)
                    return
                nome = categorias_do_tipo(self.dados, tipo)[int(selecionado[0])]
                try:
                    remover_categoria(self.dados, tipo, nome)
                except ValueError as erro:
                    messagebox.showerror("Categorias", str(erro), parent=janela)
                    return
                self.salvar_categorias(tipo)
                preencher()

            nova = ttk.Frame(area)
            nova.pack(fill="x", pady=(self.px(8), 0))
            entrada = ttk.Entry(nova, textvariable=var_nome, width=18)
            entrada.pack(side="left", fill="x", expand=True)
            entrada.bind("<Return>", lambda evento: adicionar())
            ttk.Button(nova, text="Adicionar", style="Secundario.TButton", cursor="hand2",
                       command=adicionar).pack(side="left", padx=(self.px(6), 0))
            ttk.Button(area, text="Remover selecionada", style="Perigo.TButton", cursor="hand2",
                       command=remover).pack(fill="x", pady=(self.px(6), 0))
            tabela.bind("<Delete>", lambda evento: remover())
            preencher()

        coluna("despesa", "Despesas", 0)
        coluna("receita", "Receitas", 1)

        botoes = ttk.Frame(frame)
        botoes.pack(fill="x", pady=(self.px(16), 0))
        ttk.Button(botoes, text="Fechar", style="Secundario.TButton", cursor="hand2",
                   command=janela.destroy).pack(side="right")
        self.mostrar_dialogo(janela)

    def salvar_categorias(self, tipo):
        """Salva e atualiza a lista de categorias do formulário, se for do mesmo tipo."""
        self.salvar()
        if tipo == self.tipo:
            self.mudar_tipo(self.tipo, categoria=self.var_categoria.get())


if __name__ == "__main__":
    ativar_alta_resolucao()
    AppGastos().mainloop()
