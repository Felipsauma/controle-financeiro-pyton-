"""
Testes automáticos da versão para o navegador (app_web.py).

Como rodar:  python -m unittest -v
(precisa do Flask instalado; sem ele, estes testes são pulados)

Cada teste usa uma pasta temporária (apagada no final), então o seu
gastos.json nunca é tocado.
"""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

try:
    import flask  # noqa: F401
except ImportError:
    raise unittest.SkipTest("Flask não está instalado (pip install flask)")

from app_web import chave_do_lancamento, criar_app
from financas import mes_atual

SENHA = "segredo"


class TesteSite(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.arquivo = Path(self.pasta.name) / "gastos.json"
        app = criar_app(SENHA, self.arquivo)
        app.config["TESTING"] = True
        self.cliente = app.test_client()

    def tearDown(self):
        self.pasta.cleanup()

    def entrar(self):
        self.cliente.post("/entrar", data={"senha": SENHA})

    def dados(self):
        return json.loads(self.arquivo.read_text(encoding="utf-8"))

    def escrever(self, conteudo):
        self.arquivo.write_text(json.dumps(conteudo), encoding="utf-8")

    def adicionar(self, **campos):
        formulario = {"tipo": "despesa", "valor": "25,90", "descricao": "Almoço",
                      "categoria_despesa": "Alimentação", "data": date.today().isoformat()}
        formulario.update(campos)
        return self.cliente.post("/novo", data=formulario, follow_redirects=True)

    # ---------------- Senha ----------------

    def test_sem_senha_vai_para_a_tela_de_entrar(self):
        resposta = self.cliente.get("/")
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/entrar", resposta.headers["Location"])

    def test_senha_errada_nao_entra(self):
        resposta = self.cliente.post("/entrar", data={"senha": "chute"})
        self.assertIn("Senha incorreta", resposta.get_data(as_text=True))
        self.assertEqual(self.cliente.get("/").status_code, 302)

    def test_senha_certa_entra(self):
        self.entrar()
        self.assertEqual(self.cliente.get("/").status_code, 200)

    def test_icone_abre_sem_senha(self):
        # O iPhone busca o ícone sozinho, sem a sessão de quem entrou
        resposta = self.cliente.get("/apple-touch-icon.png")
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.data.startswith(b"\x89PNG"))

    def test_sair(self):
        self.entrar()
        self.cliente.post("/sair")
        self.assertEqual(self.cliente.get("/").status_code, 302)

    # ---------------- Lançamentos ----------------

    def test_adicionar_despesa(self):
        self.entrar()
        resposta = self.adicionar(valor="1.234,56")
        pagina = resposta.get_data(as_text=True)
        self.assertIn("Almoço", pagina)
        self.assertIn("R$ 1.234,56", pagina)
        lancamento = self.dados()["lancamentos"][0]
        self.assertEqual(lancamento["valor"], 1234.56)
        self.assertEqual(lancamento["tipo"], "despesa")

    def test_adicionar_receita_usa_as_categorias_de_receita(self):
        self.entrar()
        self.adicionar(tipo="receita", descricao="Salário", categoria_receita="Salário")
        lancamento = self.dados()["lancamentos"][0]
        self.assertEqual((lancamento["tipo"], lancamento["categoria"]), ("receita", "Salário"))

    def test_valor_invalido_mostra_erro_e_nao_salva(self):
        self.entrar()
        resposta = self.adicionar(valor="abc")
        pagina = resposta.get_data(as_text=True)
        self.assertIn("Digite um número válido", pagina)
        self.assertIn('value="Almoço"', pagina)  # o que foi digitado continua no formulário
        self.assertFalse(self.arquivo.exists())

    def test_categoria_que_nao_existe_e_recusada(self):
        self.entrar()
        resposta = self.adicionar(categoria_despesa="Inventada")
        self.assertIn("Escolha uma categoria", resposta.get_data(as_text=True))

    def test_data_no_formato_brasileiro_tambem_vale(self):
        self.entrar()
        self.adicionar(data="15/10/2026")
        self.assertEqual(self.dados()["lancamentos"][0]["data"], "2026-10-15")

    def test_repetir_todo_mes_cria_recorrente(self):
        self.entrar()
        self.adicionar(descricao="Aluguel", categoria_despesa="Moradia", repetir="on")
        dados = self.dados()
        self.assertEqual(len(dados["recorrentes"]), 1)
        self.assertEqual(dados["lancamentos"][0]["recorrente"], dados["recorrentes"][0]["id"])

    def test_editar(self):
        self.entrar()
        self.adicionar()
        antigo = self.dados()["lancamentos"][0]
        self.cliente.post("/editar/0", data={
            "c": chave_do_lancamento(antigo), "tipo": "despesa", "valor": "30",
            "descricao": "Jantar", "categoria_despesa": "Alimentação", "data": antigo["data"]})
        novo = self.dados()["lancamentos"][0]
        self.assertEqual((novo["descricao"], novo["valor"]), ("Jantar", 30.0))

    def test_editar_algo_que_mudou_em_outro_lugar_nao_altera_nada(self):
        self.entrar()
        self.adicionar()
        resposta = self.cliente.post("/editar/0", data={
            "c": "impressao-velha", "tipo": "despesa", "valor": "30",
            "descricao": "Jantar", "categoria_despesa": "Alimentação"}, follow_redirects=True)
        self.assertIn("mudou ou foi removido", resposta.get_data(as_text=True))
        self.assertEqual(self.dados()["lancamentos"][0]["descricao"], "Almoço")

    def test_editar_recorrente_aplica_aos_proximos_meses_so_se_pedir(self):
        self.entrar()
        self.adicionar(descricao="Aluguel", valor="1000", categoria_despesa="Moradia", repetir="on")
        for proximos, esperado in [("", 1000.0), ("on", 1200.0)]:
            l = self.dados()["lancamentos"][0]
            self.cliente.post("/editar/0", data={
                "c": chave_do_lancamento(l), "tipo": "despesa", "valor": "1200", "descricao": "Aluguel",
                "categoria_despesa": "Moradia", "data": l["data"], "proximos": proximos})
            self.assertEqual(self.dados()["recorrentes"][0]["valor"], esperado)

    def test_remover_e_parar_de_repetir(self):
        self.entrar()
        self.adicionar(descricao="Academia", categoria_despesa="Saúde", repetir="on")
        l = self.dados()["lancamentos"][0]
        self.cliente.post("/remover/0", data={"c": chave_do_lancamento(l), "parar": "on"})
        dados = self.dados()
        self.assertEqual(dados["lancamentos"], [])
        self.assertEqual(dados["recorrentes"], [])

    def test_busca(self):
        self.entrar()
        self.adicionar(descricao="Padaria")
        self.adicionar(descricao="Cinema", categoria_despesa="Lazer")
        pagina = self.cliente.get("/?q=padaria").get_data(as_text=True)
        self.assertIn("Padaria", pagina)
        self.assertNotIn("Cinema", pagina)

    def test_lancamento_futuro_aparece_como_agendado(self):
        self.entrar()
        self.adicionar(data=f"{date.today().year + 1}-01-10")
        pagina = self.cliente.get("/?mes=todos").get_data(as_text=True)
        self.assertIn("agendado", pagina)
        self.assertIn("Com os agendados", pagina)

    def test_mes_invalido_na_endereco_vira_o_mes_atual(self):
        self.entrar()
        self.assertEqual(self.cliente.get("/?mes=abc").status_code, 200)
        self.assertEqual(self.cliente.get("/?mes=2026-13").status_code, 200)

    # ---------------- Orçamentos, recorrentes, categorias ----------------

    def test_orcamentos(self):
        self.entrar()
        self.cliente.post("/orcamentos", data={"Lazer": "300", "Alimentação": ""})
        self.assertEqual(self.dados()["orcamentos"], {"Lazer": 300.0})

        self.adicionar(descricao="Show", valor="350", categoria_despesa="Lazer")
        pagina = self.cliente.get(f"/?mes={mes_atual()}").get_data(as_text=True)
        self.assertIn("Passou R$ 50,00", pagina)

    def test_orcamento_invalido_nao_salva_nada(self):
        self.entrar()
        resposta = self.cliente.post("/orcamentos", data={"Lazer": "300", "Saúde": "xyz"})
        self.assertIn("Confira os valores", resposta.get_data(as_text=True))
        self.assertFalse(self.arquivo.exists())

    def test_parar_recorrente(self):
        self.entrar()
        self.adicionar(descricao="Netflix", categoria_despesa="Lazer", repetir="on")
        identificador = self.dados()["recorrentes"][0]["id"]
        self.assertIn("Netflix", self.cliente.get("/recorrentes").get_data(as_text=True))
        self.cliente.post(f"/recorrentes/{identificador}/parar")
        dados = self.dados()
        self.assertEqual(dados["recorrentes"], [])
        self.assertEqual(len(dados["lancamentos"]), 1)  # o que já foi criado continua

    def test_categorias(self):
        self.entrar()
        self.cliente.post("/categorias", data={"tipo": "despesa", "acao": "adicionar", "nome": "Pets"})
        self.assertIn("Pets", self.dados()["categorias"]["despesa"])

        self.adicionar(categoria_despesa="Pets")
        resposta = self.cliente.post("/categorias", follow_redirects=True,
                                     data={"tipo": "despesa", "acao": "remover", "nome": "Pets"})
        self.assertIn("não pode ser removida", resposta.get_data(as_text=True))
        self.assertIn("Pets", self.dados()["categorias"]["despesa"])

    # ---------------- Exportar e arquivos estragados ----------------

    def test_exportar_csv(self):
        self.entrar()
        self.adicionar(valor="1.234,56")
        resposta = self.cliente.get("/exportar?mes=todos")
        self.assertIn("attachment", resposta.headers["Content-Disposition"])
        texto = resposta.data.decode("utf-8-sig")
        self.assertIn("Almoço;Alimentação;-1234,56", texto)

    def test_arquivo_corrompido_e_guardado_e_avisado(self):
        self.arquivo.write_text("{ isto não é json", encoding="utf-8")
        self.entrar()
        pagina = self.cliente.get("/").get_data(as_text=True)
        self.assertIn("Nada foi apagado", pagina)
        self.assertEqual(len(list(Path(self.pasta.name).glob("gastos-corrompido-*.json"))), 1)
        # Na próxima página o aviso não se repete nem cria outro backup
        self.assertNotIn("Nada foi apagado", self.cliente.get("/").get_data(as_text=True))
        self.assertEqual(len(list(Path(self.pasta.name).glob("gastos-corrompido-*.json"))), 1)

    def test_recorrentes_vencidos_sao_criados_ao_abrir(self):
        self.escrever({"lancamentos": [], "recorrentes": [{
            "id": "abc", "tipo": "receita", "descricao": "Salário", "valor": 3500.0,
            "categoria": "Salário", "dia": 1, "ultimo_mes": "2020-01"}]})
        self.entrar()
        pagina = self.cliente.get("/").get_data(as_text=True)
        self.assertIn("adicionados automaticamente", pagina)
        self.assertGreater(len(self.dados()["lancamentos"]), 12)


if __name__ == "__main__":
    unittest.main()
