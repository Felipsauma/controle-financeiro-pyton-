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

from datetime import date

from financas import (
    ARQUIVO,
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
    formatar_numero,
    formatar_reais,
    formatar_saldo,
    gerar_recorrentes,
    mes_atual,
    parar_recorrente,
    recorrente_do_lancamento,
    remover_categoria,
    salvar_dados,
    situacao_orcamento,
    totais_por_categoria,
    totais_por_mes,
    totais_por_tipo,
    validar_data,
    validar_mes,
    validar_valor,
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


def escolher_numero(quantidade, mensagem):
    """Pede um número de 1 a 'quantidade'. Retorna a posição (0, 1, ...) ou None."""
    opcao = input(mensagem).strip()
    if opcao.isdigit() and 1 <= int(opcao) <= quantidade:
        return int(opcao) - 1
    print("Nada escolhido.")
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
        observacao = " (todo mês)" if l.get("recorrente") else ""
        if eh_futuro(l):
            observacao += " (agendado)"
        print(f"{indice + 1:>3}  {formatar_data(l['data']):<10}  {l['categoria']:<13}  "
              f"{sinal + ' ' + formatar_reais(l['valor']):>14}  {l['descricao']}{observacao}")
    print("-" * 66)
    totais = totais_por_tipo([l for _, l in itens])
    print(f"Receitas: {formatar_reais(totais['receita'])}   "
          f"Despesas: {formatar_reais(totais['despesa'])}   "
          f"Saldo: {formatar_saldo(totais['receita'] - totais['despesa'])}")


def texto_saldo(dados):
    """'R$ 1.200,00', mais o saldo previsto quando há lançamentos agendados."""
    saldo = calcular_saldo(dados["lancamentos"], ate=date.today())
    previsto = calcular_saldo(dados["lancamentos"])
    texto = formatar_saldo(saldo)
    if previsto != saldo:
        texto += f"  (previsto, com os agendados: {formatar_saldo(previsto)})"
    return texto


# ----------------------------------------------------------------------
# Salvar e carregar
# ----------------------------------------------------------------------

def carregar():
    """Carrega os dados e cria os lançamentos recorrentes que venceram."""
    try:
        dados = carregar_dados()
    except DadosCorrompidos as erro:
        dados = erro.dados
        if erro.ignorados:
            print(f"⚠ {erro.ignorados} item(ns) inválido(s) nos dados salvos foram ignorados. "
                  f"O arquivo original foi copiado para '{erro.backup.name}'.")
        else:
            print(f"⚠ Não foi possível ler os dados salvos. O arquivo antigo foi guardado como "
                  f"'{erro.backup.name}' e o programa começou com uma lista vazia.")

    criados = gerar_recorrentes(dados)
    if criados:
        salvar(dados)
        print(f"↻ {criados} lançamento(s) recorrente(s) adicionado(s) automaticamente.")
    return dados


def salvar(dados):
    """Salva os dados. Se a versão com janela mexeu no arquivo enquanto este
    programa estava aberto, pergunta qual das duas versões manter."""
    try:
        salvar_dados(dados)
    except DadosAlteradosPorFora:
        print("\n⚠ Os dados foram alterados por outro programa (a versão com janela está aberta?).")
        if confirmar("Salvar mesmo assim e descartar as mudanças feitas lá?"):
            salvar_dados(dados, forcar=True)
            return
        dados.clear()
        dados.update(carregar())
        print("Os dados foram recarregados do arquivo. A sua última alteração não foi salva.")
        return
    except OSError as erro:
        print(f"⚠ Não foi possível salvar os dados: {erro}")


# ----------------------------------------------------------------------
# Ações do menu
# ----------------------------------------------------------------------

def adicionar_lancamento(dados):
    print("\n=== Novo lançamento ===")
    tipo = escolher_tipo()
    descricao = input("Descrição (ex: almoço, salário): ").strip() or "Sem descrição"
    valor = ler_valor("Valor (R$): ")
    categoria = escolher_opcao(categorias_do_tipo(dados, tipo), "Categoria (número): ")
    data = ler_data("Data (DD/MM/AAAA, Enter = hoje): ")

    lancamento = {"tipo": tipo, "descricao": descricao, "valor": valor,
                  "categoria": categoria, "data": data}
    dados["lancamentos"].append(lancamento)
    if confirmar("Repetir todo mês, no mesmo dia?"):
        criar_recorrente(dados, lancamento)
    salvar(dados)
    print(f"✔ {tipo.capitalize()} de {formatar_reais(valor)} registrada!")


def listar_lancamentos(dados):
    print("\n=== Lançamentos ===")
    mes = ler_mes("Mês (MM/AAAA, Enter = mês atual, T = todos): ")
    print(formatar_mes(mes) if mes else "Todos os meses")
    mostrar_lancamentos(filtrar(dados["lancamentos"], mes=mes))
    print(f"Saldo atual (tudo até hoje): {texto_saldo(dados)}")


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
    indice = escolher_numero(len(dados["lancamentos"]),
                             "\nNúmero do lançamento para editar (Enter para cancelar): ")
    if indice is None:
        return

    l = dados["lancamentos"][indice]
    print("Aperte Enter para manter o valor atual.")
    tipo = escolher_tipo(atual=l["tipo"])
    descricao = ler_texto(f"Descrição [{l['descricao']}]: ", l["descricao"])
    valor = ler_valor(f"Valor [{formatar_numero(l['valor'])}]: ", atual=l["valor"])
    # Se o tipo mudou, a categoria antiga não serve mais
    categoria_atual = l["categoria"] if tipo == l["tipo"] else None
    categoria = escolher_opcao(categorias_do_tipo(dados, tipo),
                               f"Categoria [{categoria_atual or 'escolha'}]: ", atual=categoria_atual)
    data = ler_data(f"Data [{formatar_data(l['data'])}]: ", atual=l["data"])

    l.update(tipo=tipo, descricao=descricao, valor=valor, categoria=categoria, data=data)
    recorrente = recorrente_do_lancamento(dados, l)
    if recorrente and confirmar("Este lançamento se repete todo mês. Aplicar as mudanças "
                                "também aos próximos meses?"):
        atualizar_recorrente(recorrente, l)
    salvar(dados)
    print("✔ Lançamento atualizado!")


def remover_lancamento(dados):
    print("\n=== Remover lançamento ===")
    mostrar_lancamentos(filtrar(dados["lancamentos"]))
    if not dados["lancamentos"]:
        return
    indice = escolher_numero(len(dados["lancamentos"]),
                             "\nNúmero do lançamento para remover (Enter para cancelar): ")
    if indice is None:
        return
    removido = dados["lancamentos"].pop(indice)
    recorrente = recorrente_do_lancamento(dados, removido)
    if recorrente and confirmar("Este lançamento se repete todo mês. Parar de criá-lo nos próximos meses?"):
        parar_recorrente(dados, recorrente)
    salvar(dados)
    print(f"✔ Removido: {removido['descricao']} ({formatar_reais(removido['valor'])})")


def definir_orcamentos(dados):
    print("\n=== Orçamentos mensais ===")
    print("Quanto você quer gastar, no máximo, por mês em cada categoria.")
    print("Enter mantém o valor atual, 0 tira o limite.")
    for categoria in categorias_do_tipo(dados, "despesa"):
        atual = dados["orcamentos"].get(categoria)
        texto = input(f"{categoria} [{formatar_numero(atual) if atual else 'sem limite'}]: ").strip()
        if texto == "":
            continue
        try:
            valor = validar_valor(texto, aceitar_zero=True)
        except ValueError as erro:
            print(f"  {erro} (mantido o valor anterior)")
            continue
        if valor == 0:
            dados["orcamentos"].pop(categoria, None)
        else:
            dados["orcamentos"][categoria] = valor
    salvar(dados)
    print("✔ Orçamentos salvos!")


def gerenciar_recorrentes(dados):
    print("\n=== Lançamentos recorrentes ===")
    recorrentes = dados["recorrentes"]
    if not recorrentes:
        print("Nenhum lançamento recorrente. Para criar um, responda 's' em "
              "\"Repetir todo mês?\" ao adicionar um lançamento.")
        return
    for i, r in enumerate(recorrentes, start=1):
        sinal = "+" if r["tipo"] == "receita" else "-"
        print(f"{i:>3}. dia {r['dia']:>2}  {sinal} {formatar_reais(r['valor']):>13}  "
              f"{r['descricao']} ({r['categoria']})")
    indice = escolher_numero(len(recorrentes), "\nNúmero para parar de repetir (Enter para voltar): ")
    if indice is None:
        return
    r = recorrentes[indice]
    if confirmar(f"Parar de criar \"{r['descricao']}\" todo mês? Os que já foram criados continuam"):
        parar_recorrente(dados, r)
        salvar(dados)
        print("✔ Não vai mais se repetir.")


def gerenciar_categorias(dados):
    print("\n=== Categorias ===")
    tipo = escolher_tipo()
    while True:
        print(f"\nCategorias de {tipo}: {', '.join(categorias_do_tipo(dados, tipo))}")
        print("1. Adicionar   2. Remover   0. Voltar")
        opcao = input("Opção: ").strip()
        try:
            if opcao == "1":
                nome = adicionar_categoria(dados, tipo, input("Nome da nova categoria: "))
                print(f"✔ Categoria \"{nome}\" criada.")
            elif opcao == "2":
                lista = categorias_do_tipo(dados, tipo)
                for i, categoria in enumerate(lista, start=1):
                    print(f"  {i}. {categoria}")
                indice = escolher_numero(len(lista), "Número da categoria (Enter para cancelar): ")
                if indice is None:
                    continue
                nome = lista[indice]
                remover_categoria(dados, tipo, nome)
                print(f"✔ Categoria \"{nome}\" removida.")
            elif opcao == "0" or opcao == "":
                return
            else:
                print("Opção inválida.")
                continue
        except ValueError as erro:
            print(f"  {erro}")
            continue
        salvar(dados)


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
        "9": ("Lançamentos recorrentes", gerenciar_recorrentes),
        "10": ("Categorias", gerenciar_categorias),
        "11": ("Exportar para Excel (CSV)", exportar_lancamentos),
    }

    print("💰 Bem-vindo ao Controle de Gastos!")
    while True:
        print(f"\n----- MENU -----   Saldo: {texto_saldo(dados)}")
        for chave, (nome, _) in acoes.items():
            print(f"{chave:>2}. {nome}")
        print(" 0. Sair")

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
