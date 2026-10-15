# Controle de Gastos

Programa em Python para controlar as finanças pessoais. Ele registra **despesas** (o dinheiro que sai) e **receitas** (o dinheiro que entra, como o salário), mostra o saldo e ajuda a ver para onde o dinheiro está indo.

Tem duas versões, que usam os mesmos dados:

| Versão | Como abrir |
|---|---|
| Janela (interface gráfica) | `python app_gastos.py` |
| Terminal (menu de texto) | `python controle_gastos.py` |

Precisa só do Python 3.9 ou mais novo. Não é preciso instalar nenhuma biblioteca, porque tudo usa a biblioteca padrão (`tkinter`, `json`, `csv`, `unittest`).

## Funcionalidades

- **Despesas e receitas**, com categorias diferentes para cada tipo.
- **Saldo atual** e total de receitas e despesas do mês.
- **Navegação por mês** (‹ Outubro de 2026 ›) ou visão de todo o período.
- **Busca** por descrição ou categoria. A busca ignora acentos e maiúsculas: "salario" encontra "Salário".
- **Editar** um lançamento: na janela, é só dar um duplo clique na linha.
- **Orçamento por categoria**: você define um limite mensal, por exemplo "Lazer: R$ 300". A barra fica laranja quando passa de 80% do limite e vermelha quando estoura.
- **Lançamentos recorrentes**: marque "Repetir todo mês" (por exemplo, no salário e no aluguel) e o programa cria o lançamento sozinho todo mês. Se o programa ficar meses sem ser aberto, ele cria todos os meses que faltaram.
- **Gráficos**: despesas por categoria e evolução de receitas e despesas nos últimos 6 meses.
- **Exportar para Excel** (CSV com `;` e vírgula decimal, que abre direto no Excel em português).

## Organização do código

```
financas.py         regras do programa: salvar/carregar, validar, calcular, orçamentos,
                    recorrentes e exportação (nenhum print, nenhuma tela)
app_gastos.py       interface gráfica (tkinter), usa financas.py
controle_gastos.py  interface de terminal, usa financas.py
test_financas.py    testes automáticos de financas.py
gastos.json         os dados (criado automaticamente)
```

Separar as **regras** (`financas.py`) das **telas** permite que as duas versões tenham exatamente o mesmo comportamento, e que as regras sejam testadas sem abrir nenhuma janela.

## Segurança dos dados

- O arquivo é salvo primeiro numa cópia temporária, que só depois substitui o original. Se o computador desligar no meio do salvamento, o arquivo antigo continua inteiro.
- Se o `gastos.json` estiver corrompido, ele **não é apagado**: o programa o renomeia para `gastos-corrompido-<data>.json`, avisa o usuário e começa com uma lista vazia.
- Arquivos da versão antiga do programa, que guardava só uma lista de gastos, são convertidos automaticamente.

## Testes

```
python -m unittest -v
```

São 26 testes. Eles cobrem a validação de valores e datas, a formatação em reais, os cálculos de saldo e totais, a busca, os orçamentos, os lançamentos recorrentes (incluindo o dia 31 em fevereiro e anos bissextos), a exportação CSV e o comportamento com arquivos antigos ou corrompidos. Os testes usam pastas temporárias e nunca alteram o seu `gastos.json`.
