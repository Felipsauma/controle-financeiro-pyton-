# Controle de Gastos

Programa em Python para controlar as finanças pessoais. Ele registra **despesas** (o dinheiro que sai) e **receitas** (o dinheiro que entra, como o salário), mostra o saldo e ajuda a ver para onde o dinheiro está indo.

Tem três versões, que usam os mesmos dados:

| Versão | Como abrir |
|---|---|
| Janela (interface gráfica) | `python app_gastos.py` |
| Terminal (menu de texto) | `python controle_gastos.py` |
| Navegador (para usar no celular) | `python app_web.py`, ou dois cliques em `iniciar.bat` |

Precisa só do Python 3.9 ou mais novo. As versões de janela e de terminal não precisam de nenhuma biblioteca, porque usam só a biblioteca padrão (`tkinter`, `json`, `csv`, `unittest`). A versão para o navegador precisa do Flask (`pip install -r requirements.txt`).

No Windows, o jeito mais fácil é dar **dois cliques em `iniciar.bat`**: na primeira vez ele prepara o Python e instala o Flask sozinho, depois abre o programa e a página no navegador.

## Usar no celular

1. No computador, rode `python app_web.py` (ou `iniciar.bat`) e crie uma senha. Ela só é pedida na primeira vez: fica guardada em `config-web.json`, que tem apenas um resumo (hash scrypt) da senha, nunca a senha em si. Para trocar, rode `python app_web.py --nova-senha`. A senha também pode vir da variável de ambiente `CONTROLE_SENHA`.
2. O terminal mostra um endereço como `http://192.168.0.10:5000`. Abra esse endereço no navegador do celular, que precisa estar no **mesmo Wi-Fi**. Na primeira vez, o Windows pode perguntar se o Python pode usar a rede: permita em **redes privadas**.
3. Digite a senha. O celular fica conectado por 90 dias, mesmo que o programa seja fechado e aberto de novo. Trocar a senha desconecta todos os aparelhos.
4. No iPhone, toque em **Compartilhar → Adicionar à Tela de Início**. A página ganha um ícone e abre em tela cheia, como um app.

A página funciona só enquanto o programa estiver aberto no computador. Os dados são os mesmos das outras versões: o que você lança no celular aparece na janela, e o contrário também.

## Funcionalidades

- **Despesas e receitas**, com categorias diferentes para cada tipo.
- **Valores do jeito brasileiro**: `25,90`, `1.234,56` e `1.500` (mil e quinhentos) funcionam, e `1234.56` também. Textos que não são número (como `nan` ou `inf`) são recusados.
- **Categorias personalizadas**: crie as suas (por exemplo "Pets" ou "Assinaturas") ou remova as que não usa. Uma categoria com lançamentos não pode ser removida.
- **Saldo atual** e total de receitas e despesas do mês. Lançamentos com data futura aparecem como "agendado" e não entram no saldo atual, nem as contas a pagar que ainda não foram pagas; o saldo previsto, contando com eles, aparece ao lado.
- **Navegação por mês** (‹ Outubro de 2026 ›) ou visão de todo o período.
- **Busca** por descrição ou categoria. A busca ignora acentos e maiúsculas: "salario" encontra "Salário".
- **Editar** um lançamento: na janela, é só dar um duplo clique na linha.
- **Orçamento por categoria**: você define um limite mensal, por exemplo "Lazer: R$ 300". A barra fica laranja (ocre, na versão para o navegador) quando passa de 80% do limite e vermelha quando estoura.
- **Lançamentos recorrentes**: marque "Repetir todo mês" (por exemplo, no salário e no aluguel) e o programa cria o lançamento sozinho todo mês. Se o programa ficar meses sem ser aberto, ele cria todos os meses que faltaram. Ao editar um deles (o aluguel subiu, por exemplo), o programa pergunta se a mudança vale também para os próximos meses. Nas duas versões dá para ver a lista de recorrentes e parar de repetir qualquer um.
- **Gráficos**: despesas por categoria e evolução de receitas e despesas nos últimos 6 meses.
- **Exportar para Excel** (CSV com `;` e vírgula decimal, que abre direto no Excel em português).
- **Backup automático**: antes de gravar por cima dos dados, o programa guarda uma cópia do dia na pasta `backups/` (os últimos 30 dias). Vale para as três versões.

### Só na versão para o navegador

- **Compras parceladas**: lance "TV, R$ 2.400 em 10x" e as 10 parcelas são criadas, uma em cada mês. Os centavos que sobram da divisão vão para as primeiras parcelas. Ao remover uma parcela, dá para remover também as seguintes.
- **Contas a pagar**: marque "Ainda não paguei" numa despesa. Ela aparece na página inicial (em vermelho se estiver atrasada) e só entra no saldo atual quando você toca em **Paguei**. Uma conta a pagar que se repete todo mês (aluguel, luz) volta todo mês como conta a pagar.
- **Contas e cartões**: cadastre conta corrente, dinheiro e cartão de crédito e escolha em qual deles cada lançamento foi feito. No cartão, informe o dia em que a fatura fecha e o dia do vencimento: o programa mostra a fatura de cada mês e quanto do limite ainda está livre, contando as parcelas futuras.
- **Cofrinho**: guarde e retire dinheiro quando quiser, sem precisar de um objetivo. Cada movimento fica no histórico. O saldo não muda (é o mesmo das outras versões), mas a página inicial mostra quanto está guardado, no cofrinho e nas metas, e quanto sobra livre para gastar.
- **Metas de economia**: "Viagem: juntar R$ 5.000 até julho". Mostra quanto já foi guardado, quanto falta e quanto guardar por mês para chegar no prazo.
- **Comparação com o mês anterior**: quanto você gastou a mais ou a menos no mês, no total e em cada categoria.
- **Importar o extrato do banco** (OFX ou CSV): antes de salvar, você confere cada lançamento, escolhe a categoria (o programa sugere a mesma usada da última vez para aquela descrição) e os que parecem já estar na lista vêm desmarcados.
- **Ícones nas categorias**, que podem ser trocados em Mais → Categorias.
- **Desfazer**: ao remover um lançamento, aparece o botão Desfazer.
- **Visual inspirado nas cédulas do Real**: o saldo aparece como uma nota (azul, ou vermelha quando fica negativo), com gráfico de rosca das despesas e tema escuro automático.

## Organização do código

```
financas.py         regras do programa: salvar/carregar, validar, calcular, orçamentos,
                    categorias, recorrentes, parcelas, contas e cartões, metas,
                    importação e exportação (nenhum print, nenhuma tela)
app_gastos.py       interface gráfica (tkinter), usa financas.py
controle_gastos.py  interface de terminal, usa financas.py
app_web.py          versão para o navegador (Flask), usa financas.py
iniciar.bat         abre a versão para o navegador com dois cliques (Windows)
requirements.txt    bibliotecas necessárias (só o Flask)
templates/          as páginas da versão para o navegador
static/estilo.css   o visual da versão para o navegador (com tema escuro)
test_financas.py    testes automáticos de financas.py
test_app_web.py     testes automáticos da versão para o navegador
gastos.json         os dados (criado automaticamente)
config-web.json     senha (resumo) e chave da versão para o navegador (criado automaticamente)
backups/            uma cópia dos dados por dia, dos últimos 30 dias (criada automaticamente)
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

São 120 testes. Os 79 de `financas.py` cobrem a validação de valores (incluindo ponto de milhar, `nan` e valores absurdos) e datas, a formatação em reais, os cálculos de saldo e totais em centavos, os lançamentos agendados, a busca, os orçamentos, as categorias, os lançamentos recorrentes (incluindo editar, parar, o dia 31 em fevereiro e anos bissextos), as compras parceladas, as contas a pagar, as faturas e o limite do cartão, as metas, o cofrinho, a importação de extratos OFX e CSV, o backup diário, a exportação CSV, o comportamento com arquivos antigos, corrompidos ou com itens inválidos, e a proteção contra dois programas salvando ao mesmo tempo. Os testes usam pastas temporárias, que são apagadas no final, e nunca alteram o seu `gastos.json`.

Os 41 testes da versão para o navegador (`test_app_web.py`) cobrem a senha (incluindo que ela é guardada só como resumo e que o celular continua conectado quando o programa reabre), adicionar, editar e remover lançamentos (inclusive os recorrentes), a busca, os orçamentos, as categorias e os ícones, as parcelas, o desfazer, as contas a pagar, os cartões, as metas, o cofrinho, a importação de extrato, a comparação com o mês anterior, a exportação e os arquivos corrompidos. Se o Flask não estiver instalado, eles são pulados.
