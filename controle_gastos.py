"""
Controle de Gastos Pessoais - versão de terminal
------------------------------------------------
Registra despesas (dinheiro que sai) e receitas (dinheiro que entra),
mostra o saldo, as despesas por categoria comparadas com o orçamento
e quanto entrou e saiu em cada mês.

Os dados ficam salvos no arquivo "gastos.json", na mesma pasta do programa,
e são os mesmos da versão com janela (app_gastos.py).

Como rodar:  python controle_gastos.py
"""

from financas import (
    ARQUIVO,
    DadosCorrompidos,
    calcular_saldo,
    carregar_dados,
    categorias_do_tipo,
    criar_recorrente,
    dados_vazios,
    exportar_csv,
    filtrar,
    formatar_data,
    formatar_mes,
    formatar_numero,
    formatar_reais,
    formatar_saldo,
    gerar_recorrentes,
    mes_atual,
    salvar_dados,
    situacao_orcamento,
    totais_por_categoria,
    totais_por_mes,
    totais_por_tipo,
    validar_data,
    validar_mes,
    validar_valor,
    CATEGORIAS_DESPESA,
)


# ----------------------------------------------------------------------
# Funções auxiliares para ler dados do usuário com segurança
# Em todas elas, "atual" é o valor que fica se o usuário só apertar Enter
# (usado na hora de editar um lançamento).
# ----------------------------------------------------------------------

def ler_texto(mensagem, atual):
    return input(mensagem).strip() or atual


def ler_valor(mensagem, atual=None):
    """Pede um valor em reais até o usuário digitar um número positivo."""
    while True:
        texto = input(mensagem).strip()
        if texto == "" and atual is not None:
            return atual
        try:
            return validar_valor(texto)
        except ValueError as erro:
            print(f"  {erro}")


def ler_data(mensagem, atual=None):
    """Pede uma data no formato DD/MM/AAAA. Enter vazio = hoje (ou o valor atual)."""
    while True:
        texto = input(mensagem).strip()
        if texto == "" and atual is not None:
            return atual
        try:
            return validar_data(texto)
        except ValueError as erro:
            print(f"  {erro}")


def ler_mes(mensagem):
    """Pede um mês MM/AAAA. Enter = mês atual, T = todos os meses (retorna None)."""
    while True:
        texto = input(mensagem).strip()
        if texto == "":
            return mes_atual()
        if texto.lower() == "t":
            return None
        try:
            return validar_mes(texto)
        except ValueError as erro:
            print(f"  {erro}")


def escolher_opcao(opcoes, mensagem, atual=None):
    """Mostra as opções numeradas e retorna a escolhida."""
    for i, opcao in enumerate(opcoes, start=1):
        print(f"  {i}. {opcao}")
    while True:
        escolha = input(mensagem).strip()
        if escolha == "" and atual is not None:
            return atual
        if escolha.isdigit() and 1 <= int(escolha) <= len(opcoes):
            return opcoes[int(escolha) - 1]
        print("  Opção inválida.")


def escolher_tipo(atual=None):
    nome = escolher_opcao(["Despesa", "Receita"], "Tipo (número): ",
                          atual.capitalize() if atual else None)
    return nome.lower()


def confirmar(mensagem):
    return input(f"{mensagem} (s/N): ").strip().lower() == "s"


def escolher_lancamento(dados, mensagem):
    """Pede o número (#) de um lançamento. Retorna a posição na lista ou None."""
    opcao = input(mensagem).strip()
    if opcao.isdigit() and 1 <= int(opcao) <= len(dados["lancamentos"]):
        return int(opcao) - 1
    print("Nenhum lançamento escolhido.")
    return None


def mostrar_lancamentos(itens):
    """Imprime a tabela de lançamentos. 'itens' são pares (posição, lançamento)."""
    if not itens:
        print("Nenhum lançamento encontrado.")
        return
    print(f"{'#':>3}  {'Data':<10}  {'Categoria':<13}  {'Valor':>14}  Descrição")
    print("-" * 66)
    for indice, l in itens:
        sinal = "+" if l["tipo"] == "receita" else "-"
        recorrente = " (todo mês)" if l.get("recorrente") else ""
        print(f"{indice + 1:>3}  {formatar_data(l['data']):<10}  {l['categoria']:<13}  "
              f"{sinal + ' ' + formatar_reais(l['valor']):>14}  {l['descricao']}{recorrente}")
    print("-" * 66)
    totais = totais_por_tipo([l for _, l in itens])
    print(f"Receitas: {formatar_reais(totais['receita'])}   "
          f"Despesas: {formatar_reais(totais['despesa'])}   "
          f"Saldo: {formatar_saldo(totais['receita'] - totais['despesa'])}")


# ----------------------------------------------------------------------
# Ações do menu
# ----------------------------------------------------------------------

def adicionar_lancamento(dados):
    print("\n=== Novo lançamento ===")
    tipo = escolher_tipo()
    descricao = input("Descrição (ex: almoço, salário): ").strip() or "Sem descrição"
    valor = ler_valor("Valor (R$): ")
    categoria = escolher_opcao(categorias_do_tipo(tipo), "Categoria (número): ")
    data = ler_data("Data (DD/MM/AAAA, Enter = hoje): ")

    lancamento = {"tipo": tipo, "descricao": descricao, "valor": valor,
                  "categoria": categoria, "data": data}
    dados["lancamentos"].append(lancamento)
    if confirmar("Repetir todo mês, no mesmo dia?"):
        criar_recorrente(dados, lancamento)
    salvar_dados(dados)
    print(f"✔ {tipo.capitalize()} de {formatar_reais(valor)} registrada!")


def listar_lancamentos(dados):
    print("\n=== Lançamentos ===")
    mes = ler_mes("Mês (MM/AAAA, Enter = mês atual, T = todos): ")
    print(formatar_mes(mes) if mes else "Todos os meses")
    mostrar_lancamentos(filtrar(dados["lancamentos"], mes=mes))
    print(f"Saldo atual (tudo): {formatar_saldo(calcular_saldo(dados['lancamentos']))}")


def buscar_lancamentos(dados):
    print("\n=== Buscar ===")
    busca = input("Procurar por (descrição ou categoria): ").strip()
    mostrar_lancamentos(filtrar(dados["lancamentos"], busca=busca))


def despesas_por_categoria(dados):
    print("\n=== Despesas por categoria ===")
    mes = ler_mes("Mês (MM/AAAA, Enter = mês atual, T = todos): ")
    lancamentos = [l for _, l in filtrar(dados["lancamentos"], mes=mes)]
    totais = totais_por_categoria(lancamentos, "despesa")
    # Orçamentos são mensais: só fazem sentido quando um mês foi escolhido
    orcamentos = dados["orcamentos"] if mes else {}
    print(formatar_mes(mes) if mes else "Todos os meses")

    categorias = sorted(set(totais) | set(orcamentos), key=lambda c: totais.get(c, 0), reverse=True)
    if not categorias:
        print("Nenhuma despesa registrada.")
        return

    maior = max(totais.values(), default=0) or 1
    for categoria in categorias:
        gasto = totais.get(categoria, 0)
        limite = orcamentos.get(categoria)
        situacao = situacao_orcamento(gasto, limite)
        if situacao == "sem":
            barra = "█" * int(gasto / maior * 30)
            print(f"{categoria:<12} {barra:<30} {formatar_reais(gasto):>12}")
        else:
            barra = "█" * int(min(gasto / limite, 1) * 30)
            aviso = {"ok": "", "alerta": "  ⚠ quase no limite",
                     "estourado": f"  ✖ passou {formatar_reais(gasto - limite)}"}[situacao]
            print(f"{categoria:<12} {barra:<30} {formatar_reais(gasto):>12} de "
                  f"{formatar_reais(limite)}{aviso}")


def resumo_por_mes(dados):
    print("\n=== Resumo por mês ===")
    totais = totais_por_mes(dados["lancamentos"])
    if not totais:
        print("Nenhum lançamento registrado ainda.")
        return

    print(f"{'Mês':<8}  {'Receitas':>14}  {'Despesas':>14}  {'Saldo':>14}")
    for mes in sorted(totais):
        ano, numero_mes = mes.split("-")
        receitas, despesas = totais[mes]["receita"], totais[mes]["despesa"]
        print(f"{numero_mes}/{ano}   {formatar_reais(receitas):>14}  {formatar_reais(despesas):>14}  "
              f"{formatar_saldo(receitas - despesas):>14}")

    media = sum(t["despesa"] for t in totais.values()) / len(totais)
    print(f"\nMédia de despesas por mês: {formatar_reais(media)}")


def editar_lancamento(dados):
    print("\n=== Editar lançamento ===")
    mostrar_lancamentos(filtrar(dados["lancamentos"]))
    if not dados["lancamentos"]:
        return
    indice = escolher_lancamento(dados, "\nNúmero do lançamento para editar (Enter para cancelar): ")
    if indice is None:
        return

    l = dados["lancamentos"][indice]
    print("Aperte Enter para manter o valor atual.")
    tipo = escolher_tipo(atual=l["tipo"])
    descricao = ler_texto(f"Descrição [{l['descricao']}]: ", l["descricao"])
    valor = ler_valor(f"Valor [{formatar_numero(l['valor'])}]: ", atual=l["valor"])
    # Se o tipo mudou, a categoria antiga não serve mais
    categoria_atual = l["categoria"] if tipo == l["tipo"] else None
    categoria = escolher_opcao(categorias_do_tipo(tipo), f"Categoria [{categoria_atual or 'escolha'}]: ",
                               atual=categoria_atual)
    data = ler_data(f"Data [{formatar_data(l['data'])}]: ", atual=l["data"])

    l.update(tipo=tipo, descricao=descricao, valor=valor, categoria=categoria, data=data)
    salvar_dados(dados)
    print("✔ Lançamento atualizado!")


def remover_lancamento(dados):
    print("\n=== Remover lançamento ===")
    mostrar_lancamentos(filtrar(dados["lancamentos"]))
    if not dados["lancamentos"]:
        return
    indice = escolher_lancamento(dados, "\nNúmero do lançamento para remover (Enter para cancelar): ")
    if indice is None:
        return
    removido = dados["lancamentos"].pop(indice)
    salvar_dados(dados)
    print(f"✔ Removido: {removido['descricao']} ({formatar_reais(removido['valor'])})")


def definir_orcamentos(dados):
    print("\n=== Orçamentos mensais ===")
    print("Quanto você quer gastar, no máximo, por mês em cada categoria.")
    print("Enter mantém o valor atual, 0 tira o limite.")
    for categoria in CATEGORIAS_DESPESA:
        atual = dados["orcamentos"].get(categoria)
        texto = input(f"{categoria} [{formatar_numero(atual) if atual else 'sem limite'}]: ").strip()
        if texto == "":
            continue
        if texto in ("0", "0,00"):
            dados["orcamentos"].pop(categoria, None)
            continue
        try:
            dados["orcamentos"][categoria] = validar_valor(texto)
        except ValueError as erro:
            print(f"  {erro} (mantido o valor anterior)")
    salvar_dados(dados)
    print("✔ Orçamentos salvos!")


def exportar_lancamentos(dados):
    print("\n=== Exportar para CSV (Excel) ===")
    if not dados["lancamentos"]:
        print("Nenhum lançamento para exportar.")
        return
    nome = input("Nome do arquivo (Enter = lancamentos.csv): ").strip() or "lancamentos.csv"
    if not nome.lower().endswith(".csv"):
        nome += ".csv"
    caminho = ARQUIVO.parent / nome
    try:
        exportar_csv(dados["lancamentos"], caminho)
    except OSError as erro:
        print(f"Não foi possível salvar o arquivo (ele está aberto no Excel?): {erro}")
        return
    print(f"✔ {len(dados['lancamentos'])} lançamentos exportados para {caminho}")


# ----------------------------------------------------------------------
# Programa principal
# ----------------------------------------------------------------------

def carregar():
    """Carrega os dados e cria os lançamentos recorrentes que venceram."""
    try:
        dados = carregar_dados()
    except DadosCorrompidos as erro:
        print(f"⚠ Não foi possível ler os dados salvos. O arquivo antigo foi guardado como "
              f"'{erro.backup.name}' e o programa começou com uma lista vazia.")
        dados = dados_vazios()

    criados = gerar_recorrentes(dados)
    if criados:
        salvar_dados(dados)
        print(f"↻ {criados} lançamento(s) recorrente(s) adicionado(s) automaticamente.")
    return dados


def main():
    dados = carregar()

    # Dicionário que liga cada opção do menu a uma função
    acoes = {
        "1": ("Adicionar lançamento", adicionar_lancamento),
        "2": ("Listar lançamentos", listar_lancamentos),
        "3": ("Buscar", buscar_lancamentos),
        "4": ("Despesas por categoria", despesas_por_categoria),
        "5": ("Resumo por mês", resumo_por_mes),
        "6": ("Editar lançamento", editar_lancamento),
        "7": ("Remover lançamento", remover_lancamento),
        "8": ("Orçamentos", definir_orcamentos),
        "9": ("Exportar para Excel (CSV)", exportar_lancamentos),
    }

    print("💰 Bem-vindo ao Controle de Gastos!")
    while True:
        print(f"\n----- MENU -----   Saldo: {formatar_saldo(calcular_saldo(dados['lancamentos']))}")
        for chave, (nome, _) in acoes.items():
            print(f"{chave}. {nome}")
        print("0. Sair")

        escolha = input("Opção: ").strip()
        if escolha == "0":
            print("Até logo! Seus dados estão salvos em", ARQUIVO.name)
            break
        if escolha in acoes:
            _, funcao = acoes[escolha]
            funcao(dados)
        else:
            print("Opção inválida, tente de novo.")


if __name__ == "__main__":
    main()
