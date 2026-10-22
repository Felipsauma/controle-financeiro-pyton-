"""
Testes automáticos do núcleo (financas.py).

Como rodar:  python -m unittest -v

Cada teste usa uma pasta temporária (apagada no final), então o seu
gastos.json nunca é tocado.
"""

import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import financas
from financas import (
    DadosAlteradosPorFora,
    DadosCorrompidos,
    adicionar_categoria,
    atualizar_recorrente,
    calcular_saldo,
    carregar_dados,
    categorias_do_tipo,
    criar_recorrente,
    dados_vazios,
    data_no_mes,
    eh_futuro,
    exportar_csv,
    filtrar,
    formatar_mes,
    formatar_mes_curto,
    formatar_numero,
    formatar_reais,
    formatar_saldo,
    gerar_recorrentes,
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
    validar_mes,
    validar_valor,
)


def lancamento(tipo, valor, data, descricao="Teste", categoria="Outros"):
    return {"tipo": tipo, "descricao": descricao, "valor": valor, "categoria": categoria, "data": data}


class ComPastaTemporaria(unittest.TestCase):
    """Base para os testes que gravam arquivos: cria uma pasta e apaga no final."""

    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = Path(pasta.name)
        self.arquivo = self.pasta / "gastos.json"


class TesteValidacao(unittest.TestCase):
    def test_valor_aceita_virgula_e_ponto(self):
        self.assertEqual(validar_valor("25,90"), 25.9)
        self.assertEqual(validar_valor(" 1000.5 "), 1000.5)
        self.assertEqual(validar_valor("R$ 12,345"), 12.35)  # arredonda para centavos

    def test_valor_com_ponto_de_milhar(self):
        self.assertEqual(validar_valor("1.500"), 1500)       # mil e quinhentos, não 1,50
        self.assertEqual(validar_valor("1.234,56"), 1234.56)
        self.assertEqual(validar_valor("R$ 2.000.000,00"), 2000000)
        self.assertEqual(validar_valor("0.5"), 0.5)          # aqui o ponto só pode ser decimal
        self.assertEqual(validar_valor("1.50"), 1.5)

    def test_valor_arredonda_meio_centavo_para_cima(self):
        self.assertEqual(validar_valor("2,675"), 2.68)  # com float puro daria 2,67

    def test_valor_recusa_zero_negativo_e_texto(self):
        for texto in ["0", "-3", "abc", "", "0,001", "1.23,4", "1,2,3"]:
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                validar_valor(texto)

    def test_valor_recusa_nan_infinito_e_absurdos(self):
        for texto in ["nan", "NaN", "inf", "-inf", "1e5", "Infinity", "1.000.000.001"]:
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                validar_valor(texto)

    def test_valor_zero_quando_permitido(self):
        for texto in ["0", "0,00", "0.00", "0,0"]:
            with self.subTest(texto=texto):
                self.assertEqual(validar_valor(texto, aceitar_zero=True), 0)
        with self.assertRaises(ValueError):
            validar_valor("-1", aceitar_zero=True)

    def test_valor_formatado_volta_ao_mesmo_numero(self):
        for valor in [25.9, 1234.5, 1500, 0.01, 987654.32]:
            with self.subTest(valor=valor):
                self.assertEqual(validar_valor(formatar_numero(valor)), valor)

    def test_data(self):
        self.assertEqual(validar_data("15/10/2026"), "2026-10-15")
        self.assertEqual(validar_data(""), date.today().isoformat())

    def test_data_invalida(self):
        for texto in ["31/02/2026", "2026-10-15", "15/13/2026", "ontem"]:
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                validar_data(texto)

    def test_mes(self):
        self.assertEqual(validar_mes("3/2026"), "2026-03")
        with self.assertRaises(ValueError):
            validar_mes("13/2026")


class TesteFormatacao(unittest.TestCase):
    def test_reais(self):
        self.assertEqual(formatar_reais(1234.5), "R$ 1.234,50")
        self.assertEqual(formatar_reais(0), "R$ 0,00")

    def test_numero_para_edicao(self):
        self.assertEqual(formatar_numero(25.9), "25,90")
        self.assertEqual(formatar_numero(1234.5), "1.234,50")

    def test_saldo_negativo_tem_sinal(self):
        self.assertEqual(formatar_saldo(-50), "- R$ 50,00")
        self.assertEqual(formatar_saldo(50), "R$ 50,00")

    def test_meses(self):
        self.assertEqual(formatar_mes("2026-03"), "Março de 2026")
        self.assertEqual(formatar_mes_curto("2026-10"), "out/26")
        self.assertEqual(somar_meses("2026-12", 1), "2027-01")
        self.assertEqual(somar_meses("2026-01", -1), "2025-12")
        self.assertEqual(somar_meses("2026-10", -14), "2025-08")


class TesteCalculos(unittest.TestCase):
    def setUp(self):
        self.lancamentos = [
            lancamento("receita", 3000, "2026-10-05", "Salário", "Salário"),
            lancamento("despesa", 1200, "2026-10-06", "Aluguel", "Moradia"),
            lancamento("despesa", 50.5, "2026-10-10", "Pizza", "Alimentação"),
            lancamento("despesa", 100, "2026-09-20", "Mercado", "Alimentação"),
        ]

    def test_saldo(self):
        self.assertEqual(calcular_saldo(self.lancamentos), 1649.5)
        self.assertEqual(calcular_saldo([]), 0)

    def test_somas_em_centavos_nao_acumulam_erro(self):
        # Com float puro: 0.1 + 0.2 = 0.30000000000000004 e 10 x 0.1 = 0.9999999999999999
        moedas = [lancamento("receita", 0.1, "2026-10-01")] * 10 + [lancamento("receita", 0.2, "2026-10-01")]
        self.assertEqual(calcular_saldo(moedas), 1.2)
        self.assertEqual(totais_por_tipo(moedas)["receita"], 1.2)
        cafes = [lancamento("despesa", 0.1, "2026-10-01", categoria="Lazer")] * 3
        self.assertEqual(totais_por_categoria(cafes), {"Lazer": 0.3})

    def test_saldo_ate_hoje_ignora_agendados(self):
        agendado = lancamento("despesa", 500, "2026-10-25", "Conta futura")
        lista = self.lancamentos + [agendado]
        self.assertTrue(eh_futuro(agendado, hoje=date(2026, 10, 15)))
        self.assertFalse(eh_futuro(agendado, hoje=date(2026, 10, 25)))  # no próprio dia já conta
        self.assertEqual(calcular_saldo(lista, ate=date(2026, 10, 15)), 1649.5)
        self.assertEqual(calcular_saldo(lista), 1149.5)

    def test_totais_por_tipo(self):
        self.assertEqual(totais_por_tipo(self.lancamentos), {"despesa": 1350.5, "receita": 3000})

    def test_totais_por_mes(self):
        totais = totais_por_mes(self.lancamentos)
        self.assertEqual(totais["2026-10"], {"despesa": 1250.5, "receita": 3000})
        self.assertEqual(totais["2026-09"], {"despesa": 100, "receita": 0})

    def test_totais_por_categoria_ignora_receitas(self):
        self.assertEqual(totais_por_categoria(self.lancamentos),
                         {"Moradia": 1200, "Alimentação": 150.5})

    def test_filtrar_por_mes_mais_recente_primeiro(self):
        resultado = filtrar(self.lancamentos, mes="2026-10")
        self.assertEqual([l["descricao"] for _, l in resultado], ["Pizza", "Aluguel", "Salário"])

    def test_filtrar_devolve_posicao_original(self):
        indice, l = filtrar(self.lancamentos, busca="mercado")[0]
        self.assertIs(self.lancamentos[indice], l)

    def test_busca_ignora_acentos_e_maiusculas(self):
        self.assertEqual(len(filtrar(self.lancamentos, busca="SALARIO")), 1)
        self.assertEqual(len(filtrar(self.lancamentos, busca="alimentação")), 2)  # pela categoria
        self.assertEqual(filtrar(self.lancamentos, busca="xyz"), [])

    def test_situacao_orcamento(self):
        self.assertEqual(situacao_orcamento(100, None), "sem")
        self.assertEqual(situacao_orcamento(100, 300), "ok")
        self.assertEqual(situacao_orcamento(240, 300), "alerta")   # 80%
        self.assertEqual(situacao_orcamento(300, 300), "alerta")   # no limite, ainda não passou
        self.assertEqual(situacao_orcamento(300.01, 300), "estourado")


class TesteArquivo(ComPastaTemporaria):
    def escrever(self, conteudo):
        texto = conteudo if isinstance(conteudo, str) else json.dumps(conteudo)
        self.arquivo.write_text(texto, encoding="utf-8")

    def test_arquivo_inexistente_comeca_vazio(self):
        self.assertEqual(carregar_dados(self.arquivo), dados_vazios())

    def test_salvar_e_carregar(self):
        dados = dados_vazios()
        dados["lancamentos"].append(lancamento("receita", 10, "2026-10-01", "Ação", "Investimentos"))
        dados["orcamentos"]["Lazer"] = 300
        salvar_dados(dados, self.arquivo)
        self.assertEqual(carregar_dados(self.arquivo), dados)
        self.assertEqual(list(self.pasta.iterdir()), [self.arquivo])  # não sobra arquivo .tmp

    def test_converte_formato_antigo(self):
        self.escrever([{"descricao": "Uber", "valor": 20, "categoria": "Transporte", "data": "2026-10-01"}])
        dados = carregar_dados(self.arquivo)
        self.assertEqual(dados["lancamentos"][0]["tipo"], "despesa")
        self.assertEqual(dados["orcamentos"], {})
        self.assertEqual(dados["recorrentes"], [])
        self.assertEqual(dados["categorias"], dados_vazios()["categorias"])

    def test_arquivo_corrompido_vira_backup_e_nao_se_perde(self):
        self.escrever('[{"descricao": "Uber", "val')
        with self.assertRaises(DadosCorrompidos) as contexto:
            carregar_dados(self.arquivo)

        backup = contexto.exception.backup
        self.assertFalse(self.arquivo.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), '[{"descricao": "Uber", "val')
        self.assertEqual(contexto.exception.dados, dados_vazios())

        # Salvar depois disso cria um arquivo novo e não mexe no backup
        salvar_dados(dados_vazios(), self.arquivo)
        self.assertTrue(backup.exists())

    def test_itens_invalidos_sao_ignorados_e_o_resto_aproveitado(self):
        bom = lancamento("despesa", 20, "2026-10-01", "Uber", "Transporte")
        self.escrever({
            "lancamentos": [
                bom,
                {"descricao": "Sem valor", "categoria": "Lazer", "data": "2026-10-01"},
                lancamento("despesa", "20", "2026-10-01"),         # valor em texto
                lancamento("despesa", 20, "01/10/2026"),           # data no formato errado
                lancamento("transferencia", 20, "2026-10-01"),     # tipo que não existe
                "lixo",
            ],
            "orcamentos": {"Lazer": 300, "Saúde": -5},
            "recorrentes": [{"tipo": "receita", "descricao": "Salário", "valor": 3500,
                             "categoria": "Salário", "dia": 40, "ultimo_mes": "2026-10"}],
        })
        original = self.arquivo.read_text(encoding="utf-8")
        with self.assertRaises(DadosCorrompidos) as contexto:
            carregar_dados(self.arquivo)

        erro = contexto.exception
        self.assertEqual(erro.ignorados, 7)
        self.assertEqual(erro.dados["lancamentos"], [bom])
        self.assertEqual(erro.dados["orcamentos"], {"Lazer": 300})
        self.assertEqual(erro.dados["recorrentes"], [])
        # O original continua no lugar e também foi copiado para o backup
        self.assertEqual(self.arquivo.read_text(encoding="utf-8"), original)
        self.assertEqual(erro.backup.read_text(encoding="utf-8"), original)

    def test_secoes_com_tipo_errado(self):
        self.escrever({"lancamentos": None, "orcamentos": [], "recorrentes": {}})
        with self.assertRaises(DadosCorrompidos) as contexto:
            carregar_dados(self.arquivo)
        self.assertEqual(contexto.exception.ignorados, 3)
        self.assertEqual(contexto.exception.dados, dados_vazios())

    def test_nan_no_arquivo_e_ignorado(self):
        self.escrever('{"lancamentos": [{"tipo": "despesa", "descricao": "x", "valor": NaN, '
                      '"categoria": "Lazer", "data": "2026-10-01"}]}')
        with self.assertRaises(DadosCorrompidos) as contexto:
            carregar_dados(self.arquivo)
        self.assertEqual(contexto.exception.dados["lancamentos"], [])

    def test_nao_grava_nan(self):
        dados = dados_vazios()
        dados["lancamentos"].append(lancamento("despesa", float("nan"), "2026-10-01"))
        with self.assertRaises(ValueError):
            salvar_dados(dados, self.arquivo)

    def test_percebe_quando_outro_programa_alterou_o_arquivo(self):
        salvar_dados(dados_vazios(), self.arquivo)
        dados = carregar_dados(self.arquivo)

        # A outra versão do programa salva um lançamento enquanto esta estava aberta
        outra = dados_vazios()
        outra["lancamentos"].append(lancamento("despesa", 99, "2026-10-01", "Feito na outra janela"))
        self.escrever(outra)

        dados["orcamentos"]["Lazer"] = 300
        with self.assertRaises(DadosAlteradosPorFora):
            salvar_dados(dados, self.arquivo)
        self.assertEqual(carregar_dados(self.arquivo), outra)  # nada foi perdido

        # Recarregou: agora pode salvar normalmente
        salvar_dados(carregar_dados(self.arquivo), self.arquivo)

    def test_forcar_salva_mesmo_com_alteracao_de_fora(self):
        dados = carregar_dados(self.arquivo)
        self.escrever(dados_vazios())
        salvar_dados(dados, self.arquivo, forcar=True)
        salvar_dados(dados, self.arquivo)  # e depois disso segue normal

    def test_salvamentos_seguidos_nao_dao_conflito(self):
        dados = carregar_dados(self.arquivo)
        for i in range(5):
            dados["orcamentos"]["Lazer"] = 100 + i
            salvar_dados(dados, self.arquivo)

    def test_caminho_padrao_e_o_arquivo_do_modulo(self):
        self.assertEqual(financas.ARQUIVO.name, "gastos.json")


class TesteCategorias(ComPastaTemporaria):
    def setUp(self):
        super().setUp()
        self.dados = dados_vazios()

    def test_padrao_e_copia_independente(self):
        categorias_do_tipo(self.dados, "despesa").append("Pets")
        self.assertNotIn("Pets", dados_vazios()["categorias"]["despesa"])
        self.assertNotIn("Pets", financas.CATEGORIAS_DESPESA)

    def test_adicionar(self):
        self.assertEqual(adicionar_categoria(self.dados, "despesa", "  Pets   e  bichos "), "Pets e bichos")
        self.assertIn("Pets e bichos", categorias_do_tipo(self.dados, "despesa"))
        self.assertNotIn("Pets e bichos", categorias_do_tipo(self.dados, "receita"))

    def test_adicionar_recusa_repetida_vazia_e_longa(self):
        for nome in ["saude", "LAZER", "", "   ", "x" * 31]:
            with self.subTest(nome=nome), self.assertRaises(ValueError):
                adicionar_categoria(self.dados, "despesa", nome)

    def test_remover(self):
        self.dados["orcamentos"]["Lazer"] = 300
        remover_categoria(self.dados, "despesa", "Lazer")
        self.assertNotIn("Lazer", categorias_do_tipo(self.dados, "despesa"))
        self.assertNotIn("Lazer", self.dados["orcamentos"])

    def test_nao_remove_categoria_em_uso(self):
        self.dados["lancamentos"].append(lancamento("despesa", 10, "2026-10-01", categoria="Lazer"))
        with self.assertRaises(ValueError):
            remover_categoria(self.dados, "despesa", "Lazer")
        # A mesma categoria do outro tipo não conta como uso
        remover_categoria(self.dados, "receita", "Outros")

    def test_nao_remove_a_ultima(self):
        self.dados["categorias"]["receita"] = ["Salário"]
        with self.assertRaises(ValueError):
            remover_categoria(self.dados, "receita", "Salário")

    def test_categorias_sao_salvas(self):
        adicionar_categoria(self.dados, "receita", "Aluguel recebido")
        salvar_dados(self.dados, self.arquivo)
        self.assertIn("Aluguel recebido", categorias_do_tipo(carregar_dados(self.arquivo), "receita"))

    def test_categoria_usada_que_nao_esta_na_lista_e_acrescentada(self):
        self.dados["categorias"]["despesa"] = ["Moradia"]
        self.dados["lancamentos"].append(lancamento("despesa", 10, "2026-10-01", categoria="Viagem"))
        salvar_dados(self.dados, self.arquivo)
        self.assertEqual(categorias_do_tipo(carregar_dados(self.arquivo), "despesa"), ["Moradia", "Viagem"])


class TesteRecorrentes(ComPastaTemporaria):
    def setUp(self):
        super().setUp()
        self.dados = dados_vazios()
        self.salario = lancamento("receita", 3500, "2026-08-05", "Salário", "Salário")
        self.dados["lancamentos"].append(self.salario)
        self.recorrente = criar_recorrente(self.dados, self.salario)

    def test_cria_os_meses_que_faltaram(self):
        criados = gerar_recorrentes(self.dados, hoje=date(2026, 10, 15))
        self.assertEqual(criados, 2)
        datas = [l["data"] for l in self.dados["lancamentos"]]
        self.assertEqual(datas, ["2026-08-05", "2026-09-05", "2026-10-05"])
        self.assertTrue(all(l["recorrente"] for l in self.dados["lancamentos"]))

    def test_lancamentos_ficam_ligados_ao_recorrente(self):
        gerar_recorrentes(self.dados, hoje=date(2026, 10, 15))
        for l in self.dados["lancamentos"]:
            self.assertIs(recorrente_do_lancamento(self.dados, l), self.recorrente)
        avulso = lancamento("despesa", 10, "2026-10-01")
        self.assertIsNone(recorrente_do_lancamento(self.dados, avulso))

    def test_nao_cria_antes_do_dia(self):
        self.assertEqual(gerar_recorrentes(self.dados, hoje=date(2026, 9, 4)), 0)
        self.assertEqual(gerar_recorrentes(self.dados, hoje=date(2026, 9, 5)), 1)

    def test_nao_duplica_ao_abrir_de_novo(self):
        gerar_recorrentes(self.dados, hoje=date(2026, 10, 15))
        self.assertEqual(gerar_recorrentes(self.dados, hoje=date(2026, 10, 15)), 0)
        self.assertEqual(len(self.dados["lancamentos"]), 3)

    def test_editar_e_aplicar_aos_proximos_meses(self):
        # O salário subiu e passou a cair no dia 7
        self.salario.update(valor=4000, data="2026-08-07")
        atualizar_recorrente(self.recorrente, self.salario)
        gerar_recorrentes(self.dados, hoje=date(2026, 9, 30))
        novo = self.dados["lancamentos"][-1]
        self.assertEqual((novo["valor"], novo["data"]), (4000, "2026-09-07"))

    def test_parar_de_repetir(self):
        parar_recorrente(self.dados, self.recorrente)
        self.assertEqual(gerar_recorrentes(self.dados, hoje=date(2026, 12, 31)), 0)
        self.assertEqual(len(self.dados["lancamentos"]), 1)  # o que já existia continua
        self.assertIsNone(recorrente_do_lancamento(self.dados, self.salario))

    def test_arquivo_antigo_sem_id_e_ligado_pelo_nome(self):
        self.escrever_antigo()
        dados = carregar_dados(self.arquivo)
        recorrente = dados["recorrentes"][0]
        self.assertTrue(recorrente["id"])
        self.assertIs(recorrente_do_lancamento(dados, dados["lancamentos"][0]), recorrente)
        self.assertIs(dados["lancamentos"][1]["recorrente"], True)  # o recorrente dele já foi parado

    def escrever_antigo(self):
        self.arquivo.write_text(json.dumps({
            "lancamentos": [
                dict(lancamento("receita", 3500, "2026-10-05", "Salário", "Salário"), recorrente=True),
                dict(lancamento("despesa", 50, "2026-10-01", "Academia", "Saúde"), recorrente=True),
            ],
            "recorrentes": [{"tipo": "receita", "descricao": "Salário", "valor": 3500,
                             "categoria": "Salário", "dia": 5, "ultimo_mes": "2026-10"}],
        }), encoding="utf-8")

    def test_dia_31_em_mes_curto(self):
        self.assertEqual(data_no_mes("2026-02", 31), date(2026, 2, 28))
        self.assertEqual(data_no_mes("2028-02", 31), date(2028, 2, 29))  # ano bissexto

        dados = dados_vazios()
        aluguel = lancamento("despesa", 1200, "2026-01-31", "Aluguel", "Moradia")
        dados["lancamentos"].append(aluguel)
        criar_recorrente(dados, aluguel)
        gerar_recorrentes(dados, hoje=date(2026, 3, 31))
        self.assertEqual([l["data"] for l in dados["lancamentos"]],
                         ["2026-01-31", "2026-02-28", "2026-03-31"])


class TesteExportacao(ComPastaTemporaria):
    def test_csv_para_excel(self):
        caminho = self.pasta / "saida.csv"
        exportar_csv([
            lancamento("despesa", 1234.5, "2026-10-10", "Aluguel; outubro", "Moradia"),
            lancamento("receita", 3000, "2026-10-05", "Salário", "Salário"),
        ], caminho)

        conteudo = caminho.read_bytes()
        self.assertTrue(conteudo.startswith(b"\xef\xbb\xbf"))  # BOM: Excel reconhece os acentos
        with open(caminho, encoding="utf-8-sig", newline="") as f:
            linhas = list(csv.reader(f, delimiter=";"))
        self.assertEqual(linhas, [
            ["Data", "Tipo", "Descrição", "Categoria", "Valor"],
            ["05/10/2026", "Receita", "Salário", "Salário", "3000,00"],
            ["10/10/2026", "Despesa", "Aluguel; outubro", "Moradia", "-1234,50"],
        ])


if __name__ == "__main__":
    unittest.main()
