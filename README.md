# Controle de Gastos

Programa em Python para controlar as finanças pessoais. Ele registra **despesas** (o dinheiro que sai) e **receitas** (o dinheiro que entra, como o salário), mostra o saldo e ajuda a ver para onde o dinheiro está indo.

Tem três versões, que usam os mesmos dados:

| Versão | Como abrir |
|---|---|
| Janela (interface gráfica) | `python app_gastos.py` |
| Terminal (menu de texto) | `python controle_gastos.py` |
| Navegador (para usar no celular) | `python app_web.py` |

Precisa só do Python 3.9 ou mais novo. As versões de janela e de terminal não precisam de nenhuma biblioteca, porque usam só a biblioteca padrão (`tkinter`, `json`, `csv`, `unittest`). A versão para o navegador precisa do Flask (`pip install flask`).

## Usar no celular

1. No computador, rode `python app_web.py` e crie uma senha. Ela é pedida sempre que o programa abre, ou pode vir da variável de ambiente `CONTROLE_SENHA`.
2. O terminal mostra um endereço como `http://192.168.0.10:5000`. Abra esse endereço no navegador do celular, que precisa estar no **mesmo Wi-Fi**. Na primeira vez, o Windows pode perguntar se o Python pode usar a rede: permita em **redes privadas**.
3. Digite a senha. O celular fica conectado por 90 dias, ou até o programa ser fechado e aberto de novo.
4. No iPhone, toque em **Compartilhar → Adicionar à Tela de Início**. A página ganha um ícone e abre em tela cheia, como um app.

A página funciona só enquanto o programa estiver aberto no computador. Os dados são os mesmos das outras versões: o que você lança no celular aparece na janela, e o contrário também.

## Funcionalidades

- **Despesas e receitas**, com categorias diferentes para cada tipo.
- **Valores do jeito brasileiro**: `25,90`, `1.234,56` e `1.500` (mil e quinhentos) funcionam, e `1234.56` também. Textos que não são número (como `nan` ou `inf`) são recusados.
- **Categorias personalizadas**: crie as suas (por exemplo "Pets" ou "Assinaturas") ou remova as que não usa. Uma categoria com lançamentos não pode ser removida.
- **Saldo atual** e total de receitas e despesas do mês. Lançamentos com data futura aparecem como "agendado" e não entram no saldo atual; o saldo previsto, contando com eles, aparece ao lado.
- **Navegação por mês** (‹ Outubro de 2026 ›) ou visão de todo o período.
- **Busca** por descrição ou categoria. A busca ignora acentos e maiúsculas: "salario" encontra "Salário".
- **Editar** um lançamento: na janela, é só dar um duplo clique na linha.
- **Orçamento por categoria**: você define um limite mensal, por exemplo "Lazer: R$ 300". A barra fica laranja quando passa de 80% do limite e vermelha quando estoura.
- **Lançamentos recorrentes**: marque "Repetir todo mês" (por exemplo, no salário e no aluguel) e o programa cria o lançamento sozinho todo mês. Se o programa ficar meses sem ser aberto, ele cria todos os meses que faltaram. Ao editar um deles (o aluguel subiu, por exemplo), o programa pergunta se a mudança vale também para os próximos meses. Nas duas versões dá para ver a lista de recorrentes e parar de repetir qualquer um.
- **Gráficos**: despesas por categoria e evolução de receitas e despesas nos últimos 6 meses.
- **Exportar para Excel** (CSV com `;` e vírgula decimal, que abre direto no Excel em português).

## Organização do código

```
financas.py         regras do programa: salvar/carregar, validar, calcular, orçamentos,
                    categorias, recorrentes e exportação (nenhum print, nenhuma tela)
app_gastos.py       interface gráfica (tkinter), usa financas.py
controle_gastos.py  interface de terminal, usa financas.py
app_web.py          versão para o navegador (Flask), usa financas.py
templates/          as páginas da versão para o navegador
static/estilo.css   o visual da versão para o navegador (com tema escuro)
test_financas.py    testes automáticos de financas.py
test_app_web.py     testes automáticos da versão para o navegador
gastos.json         os dados (criado automaticamente)
```

Separar as **regras** (`financas.py`) das **telas** permite que as duas versões tenham exatamente o mesmo comportamento, e que as regras sejam testadas sem abrir nenhuma janela.

## Segurança dos dados

- O arquivo é salvo primeiro numa cópia temporária, que só depois substitui o original. Se o computador desligar no meio do salvamento, o arquivo antigo continua inteiro.
- Se o `gastos.json` estiver corrompido, ele **não é apagado**: o programa o renomeia para `gastos-corrompido-<data>.json`, avisa o usuário e começa com uma lista vazia.
- Se só alguns itens do arquivo estiverem inválidos (um valor que não é número, uma data errada...), o programa aproveita o resto, guarda uma cópia do arquivo original e avisa quantos itens foram ignorados.
- Se a versão de terminal e a versão com janela estiverem abertas ao mesmo tempo, uma não apaga o que a outra salvou: antes de salvar, o programa percebe que o arquivo mudou e pergunta qual versão manter.
- Os valores são somados em centavos (números inteiros), então os totais não acumulam erros de arredondamento.
- Arquivos da versão antiga do programa, que guardava só uma lista de gastos, são convertidos automaticamente.

## Testes

```
python -m unittest -v
```

São 78 testes. Os de `financas.py` cobrem a validação de valores (incluindo ponto de milhar, `nan` e valores absurdos) e datas, a formatação em reais, os cálculos de saldo e totais em centavos, os lançamentos agendados, a busca, os orçamentos, as categorias, os lançamentos recorrentes (incluindo editar, parar, o dia 31 em fevereiro e anos bissextos), a exportação CSV, o comportamento com arquivos antigos, corrompidos ou com itens inválidos, e a proteção contra dois programas salvando ao mesmo tempo. Os testes usam pastas temporárias, que são apagadas no final, e nunca alteram o seu `gastos.json`.

Os 25 testes da versão para o navegador (`test_app_web.py`) cobrem a senha, adicionar, editar e remover lançamentos (inclusive os recorrentes), a busca, os orçamentos, as categorias, a exportação e os arquivos corrompidos. Se o Flask não estiver instalado, eles são pulados.
