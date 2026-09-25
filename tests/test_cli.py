"""Testes do entry point ``tecmente`` (tecmente_cli.py).

O CLI não tinha nenhum teste. O risco concreto é silencioso: se um script da
raiz for renomeado ou removido, ``_SCRIPTS`` passa a apontar para um caminho
inexistente e o comando falha apenas em tempo de execução, na máquina do
usuário — sem nenhum sinal em CI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tecmente import tecmente_cli

# =============================================================================
# Integridade do mapa de comandos
# =============================================================================


class TestMapaComandos:
    def test_todos_os_comandos_apontam_para_scripts_existentes(self) -> None:
        """Regressão: um script renomeado quebraria o entry point em silêncio."""
        inexistentes = {
            comando: script
            for comando, script in tecmente_cli._SCRIPTS.items()
            if not (tecmente_cli._PROJETO_ROOT / script).exists()
        }
        assert not inexistentes, f"Scripts ausentes: {inexistentes}"

    def test_comandos_esperados_documentados_no_agents(self) -> None:
        esperado = {
            "gerar",
            "extrair",
            "tratar",
            "visualizar",
            "interativo",
            "prever",
            "bi",
            "validar",
            "pipeline",
        }
        assert set(tecmente_cli._SCRIPTS) == esperado

    def test_comandos_apontam_para_a_raiz_do_projeto(self) -> None:
        for comando, script in tecmente_cli._SCRIPTS.items():
            alvo = (tecmente_cli._PROJETO_ROOT / script).resolve()
            assert alvo.parent == Path(tecmente_cli._PROJETO_ROOT).resolve(), comando


# =============================================================================
# main()
# =============================================================================


@pytest.fixture
def run_fake(monkeypatch):
    """Intercepta subprocess.run e registra o comando montado."""
    chamadas: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        chamadas.append(list(cmd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(tecmente_cli.subprocess, "run", fake_run)
    return chamadas


class TestMain:
    def test_encaminha_comando_para_o_script_correto(
        self, run_fake, monkeypatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["tecmente", "tratar"])
        with pytest.raises(SystemExit) as exc:
            tecmente_cli.main()
        assert exc.value.code == 0
        cmd = run_fake[0]
        assert Path(cmd[1]).name == "tratador.py"
        assert cmd[0] == sys.executable

    def test_repassa_args_com_hifen_para_o_script(self, run_fake, monkeypatch) -> None:
        """Regressão do pass-through: o CLI precisa aceitar flags com hífen
        sem tratar o "--" como erro próprio. Era o que a docstring anunciava.
        """
        monkeypatch.setattr(sys, "argv", ["tecmente", "prever", "--dias_prever", "3"])
        with pytest.raises(SystemExit):
            tecmente_cli.main()
        assert run_fake[0][2:] == ["--dias_prever", "3"]

    def test_repassa_args_apos_separador_duplo(self, run_fake, monkeypatch) -> None:
        monkeypatch.setattr(
            sys, "argv", ["tecmente", "visualizar", "--", "--fonte", "sql"]
        )
        with pytest.raises(SystemExit):
            tecmente_cli.main()
        assert run_fake[0][2:] == ["--fonte", "sql"]

    def test_propaga_returncode_de_sucesso(self, monkeypatch) -> None:
        monkeypatch.setattr(
            tecmente_cli.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=0),
        )
        monkeypatch.setattr(sys, "argv", ["tecmente", "tratar"])
        with pytest.raises(SystemExit) as exc:
            tecmente_cli.main()
        assert exc.value.code == 0

    def test_propaga_returncode_de_erro(self, monkeypatch) -> None:
        """O returncode alimenta o Task Scheduler: erro precisa propagar."""
        monkeypatch.setattr(
            tecmente_cli.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=3),
        )
        monkeypatch.setattr(sys, "argv", ["tecmente", "pipeline"])
        with pytest.raises(SystemExit) as exc:
            tecmente_cli.main()
        assert exc.value.code == 3

    def test_sai_com_1_sem_chamar_subprocess_quando_script_some(
        self, monkeypatch, capsys
    ) -> None:
        monkeypatch.setattr(tecmente_cli, "_SCRIPTS", {"x": "nao_existe.py"})
        chamadas: list = []

        def fake_run(*a, **k):  # pragma: no cover - não deve ser chamado
            chamadas.append(a)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(tecmente_cli.subprocess, "run", fake_run)
        monkeypatch.setattr(sys, "argv", ["tecmente", "x"])
        with pytest.raises(SystemExit) as exc:
            tecmente_cli.main()
        assert exc.value.code == 1
        assert not chamadas, "subprocess não deveria rodar com script ausente"
        assert "não encontrado" in capsys.readouterr().err

    def test_comando_invalido_aciona_help(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["tecmente", "comando_inexistente"])
        with pytest.raises(SystemExit) as exc:
            tecmente_cli.main()
        assert exc.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_help_lista_os_nove_comandos(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["tecmente", "--help"])
        with pytest.raises(SystemExit) as exc:
            tecmente_cli.main()
        assert exc.value.code == 0
        saida = capsys.readouterr().out
        for comando in tecmente_cli._SCRIPTS:
            assert comando in saida
