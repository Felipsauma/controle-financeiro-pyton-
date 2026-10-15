"""
Testes automáticos do núcleo (financas.py).

Como rodar:  python -m unittest -v

Cada teste usa uma pasta temporária, então o seu gastos.json nunca é tocado.
"""

import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import financas
from financas import (
    DadosCorrompidos,
    calcular_saldo,
    carregar_dados,
    criar_recorrente,
    dados_vazios,
    data_no_mes,
    exportar_csv,
    filtrar,
    formatar_mes,
    formatar_mes_curto,
    formatar_reais,
    formatar_saldo,
    gerar_recorrentes,
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


class TesteValidacao(unittest.TestCase):
    def test_valor_aceita_virgula_e_ponto(self):
        self.assertEqual(validar_valor("25,90"), 25.9)
        self.assertEqual(validar_valor(" 1000.5 "), 1000.5)
        self.assertEqual(validar_valor("R$ 12,345"), 12.35)  # arredonda para centavos

    def test_valor_recusa_zero_negativo_e_texto(self):
        for texto in ["0", "-3", "abc", ""]:
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                validar_valor(texto)

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


class TesteArquivo(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.arquivo = self.pasta / "gastos.json"

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
        antigo = [{"descricao": "Uber", "valor": 20, "categoria": "Transporte", "data": "2026-10-01"}]
        self.arquivo.write_text(json.dumps(antigo), encoding="utf-8")
        dados = carregar_dados(self.arquivo)
        self.assertEqual(dados["lancamentos"][0]["tipo"], "despesa")
        self.assertEqual(dados["orcamentos"], {})
        self.assertEqual(dados["recorrentes"], [])

    def test_arquivo_corrompido_vira_backup_e_nao_se_perde(self):
        self.arquivo.write_text('[{"descricao": "Uber", "val', encoding="utf-8")
        with self.assertRaises(DadosCorrompidos) as contexto:
            carregar_dados(self.arquivo)

        backup = contexto.exception.backup
        self.assertFalse(self.arquivo.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), '[{"descricao": "Uber", "val')

        # Salvar depois disso cria um arquivo novo e não mexe no backup
        salvar_dados(dados_vazios(), self.arquivo)
        self.assertTrue(backup.exists())

    def test_caminho_padrao_e_o_arquivo_do_modulo(self):
        self.assertEqual(financas.ARQUIVO.name, "gastos.json")


class TesteRecorrentes(unittest.TestCase):
    def setUp(self):
        self.dados = dados_vazios()
        salario = lancamento("receita", 3500, "2026-08-05", "Salário", "Salário")
        self.dados["lancamentos"].append(salario)
        criar_recorrente(self.dados, salario)

    def test_cria_os_meses_que_faltaram(self):
        criados = gerar_recorrentes(self.dados, hoje=date(2026, 10, 15))
        self.assertEqual(criados, 2)
        datas = [l["data"] for l in self.dados["lancamentos"]]
        self.assertEqual(datas, ["2026-08-05", "2026-09-05", "2026-10-05"])
        self.assertTrue(all(l["recorrente"] for l in self.dados["lancamentos"]))

    def test_nao_cria_antes_do_dia(self):
        self.assertEqual(gerar_recorrentes(self.dados, hoje=date(2026, 9, 4)), 0)
        self.assertEqual(gerar_recorrentes(self.dados, hoje=date(2026, 9, 5)), 1)

    def test_nao_duplica_ao_abrir_de_novo(self):
        gerar_recorrentes(self.dados, hoje=date(2026, 10, 15))
        self.assertEqual(gerar_recorrentes(self.dados, hoje=date(2026, 10, 15)), 0)
        self.assertEqual(len(self.dados["lancamentos"]), 3)

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


class TesteExportacao(unittest.TestCase):
    def test_csv_para_excel(self):
        caminho = Path(tempfile.mkdtemp()) / "saida.csv"
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
