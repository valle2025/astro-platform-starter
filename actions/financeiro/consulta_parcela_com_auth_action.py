from typing import Any, Dict, Optional
import time
import httpx

from tech4ai.actions.sdk.action_span import ActionSpan
from tech4ai.actions.sdk.response_objects import ActionSuccess, ActionFailure, ActionResult
from tech4ai.actions.sdk.memory_management import get_session_memory, set_session_memory

# ======================================================================================
# CONFIG INTERNA (ajuste se precisar)
# ======================================================================================

# Endpoint de OAuth (username/password)
AUTH_URL = "https://portoapi-hml.portoseguro.com.br/oauth/v2/access-token"
AUTH_USERNAME = "cd49436f-2074-4c47-8546-c403e4a4d4a6"
AUTH_PASSWORD = "a5a49c7a-1a9b-49c5-b118-8ce34e7dbf28"
AUTH_GRANT_TYPE = "password"
AUTH_TIMEOUT = 20

# Endpoint de negócio (GET)
FINANCEIRO_URL = "https://portoapi-hml.portoseguro.com.br/financeiro/sap/v1/dados-gerais-parcela/consulta"
FINANCEIRO_TIMEOUT = 25

# Parâmetros FIXOS da consulta
TIPO_CONSULTA = "3"
SISTEMA_ORIGEM = "SUPERAPP"
CODIGO_TIPO_PRODUTO = "01"

# Chaves de memória
MEM_TOKEN_KEY = "porto_auth_bearer_token"
MEM_EXPIRES_AT_KEY = "porto_auth_bearer_expires_at"

# ======================================================================================
# HELPERS: OBTÉM/RENOVA TOKEN E CHAMA O ENDPOINT
# ======================================================================================

def _obter_token() -> ActionResult:
    with ActionSpan(name="_obter_token") as span:
        try:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }
            data = {
                "grant_type": AUTH_GRANT_TYPE,
                "username": AUTH_USERNAME,
                "password": AUTH_PASSWORD,
            }

            span.add_tags({"url": AUTH_URL, "method": "POST", "grant_type": AUTH_GRANT_TYPE})

            with httpx.Client(timeout=AUTH_TIMEOUT) as client:
                resp = client.post(AUTH_URL, headers=headers, data=data)

            ok = 200 <= resp.status_code < 300
            span.add_tags({"status_code": resp.status_code, "ok": ok})

            try:
                payload = resp.json()
            except Exception:
                payload = {"raw_text": resp.text}

            if not ok:
                return ActionFailure(
                    message="Falha ao obter token",
                    code="AUTH_UPSTREAM_ERROR",
                    data=payload,  # retorna payload bruto de erro
                )

            token = payload.get("access_token")
            expires_in = payload.get("expires_in")

            if not token:
                return ActionFailure(
                    message="Campo 'access_token' ausente na resposta de auth",
                    code="TOKEN_MISSING",
                    data=payload,  # retorna payload bruto para debug
                )

            now = int(time.time())
            expires_at = now + (int(expires_in) - 30 if isinstance(expires_in, int) and expires_in > 0 else 600)

            set_session_memory(MEM_TOKEN_KEY, token)
            set_session_memory(MEM_EXPIRES_AT_KEY, expires_at)

            # Retorna apenas o necessário; você pode querer o payload também:
            return ActionSuccess(message="Token obtido com sucesso", data={"access_token": token, "expires_at": expires_at})

        except httpx.TimeoutException as e:
            span.record_exception(e)
            return ActionFailure(message="Timeout no endpoint de auth", code="AUTH_TIMEOUT")
        except Exception as e:
            span.record_exception(e)
            return ActionFailure(message="Erro inesperado ao obter token", code="AUTH_UNEXPECTED_ERROR", data={"error": str(e)})

def _garantir_token_valido() -> ActionResult:
    with ActionSpan(name="_garantir_token_valido") as span:
        now = int(time.time())
        token = get_session_memory(MEM_TOKEN_KEY)
        expires_at = get_session_memory(MEM_EXPIRES_AT_KEY) or 0

        if token and now < int(expires_at):
            return ActionSuccess(message="Token válido em cache", data={"token": token})

        res = _obter_token()
        if isinstance(res, ActionFailure):
            return res

        token = get_session_memory(MEM_TOKEN_KEY)
        if not token:
            return ActionFailure(message="Token ausente após renovação", code="TOKEN_RENEWAL_FAILED")

        return ActionSuccess(message="Token renovado", data={"token": token})

def _chamar_financeiro(
    *,
    token: str,
    apolice: str,
) -> ActionResult:
    with ActionSpan(name="_chamar_financeiro") as span:
        try:
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            }
            params = {
                "tipoConsulta": TIPO_CONSULTA,
                "sistemaOrigem": SISTEMA_ORIGEM,
                "codigoTipoProduto": CODIGO_TIPO_PRODUTO,
                "apolice": apolice,
            }

            span.add_tags({"url": FINANCEIRO_URL, "method": "GET"})

            with httpx.Client(timeout=FINANCEIRO_TIMEOUT) as client:
                resp = client.get(FINANCEIRO_URL, headers=headers, params=params)

            ok = 200 <= resp.status_code < 300
            span.add_tags({"status_code": resp.status_code, "ok": ok})

            # Tenta JSON; se não der, traz texto cru
            try:
                payload = resp.json()
            except Exception:
                payload = {"raw_text": resp.text}

            if ok:
                # SUCESSO: devolve o JSON bruto da API
                return ActionSuccess(
                    message="Consulta realizada com sucesso",
                    data=payload,
                )
            else:
                # ERRO: devolve o JSON/texto bruto de erro
                return ActionFailure(
                    message="Erro ao consultar endpoint financeiro",
                    code="UPSTREAM_ERROR",
                    data=payload,
                )

        except httpx.TimeoutException as e:
            span.record_exception(e)
            return ActionFailure(message="Timeout no endpoint financeiro", code="TIMEOUT")
        except Exception as e:
            span.record_exception(e)
            return ActionFailure(message="Erro inesperado na chamada financeira", code="UNEXPECTED_ERROR", data={"error": str(e)})

# ======================================================================================
# ACTION PRINCIPAL — EXPONHA NA SUA FERRAMENTA
# ======================================================================================

def consulta_parcela_com_auth_action(
    *,
    apolice: str,  # obrigatório
) -> ActionResult:
    """
    - Recebe apólice (obrigatório).
    - Garante bearer token válido (cache em session memory).
    - Executa GET com parâmetros fixos: tipoConsulta=3, sistemaOrigem=SUPERAPP, codigoTipoProduto=01, e apolice recebido.
    - Retorna o JSON bruto (ou texto) da API em caso de sucesso; e o payload bruto de erro em caso de falha.
    """
    with ActionSpan(name="consulta_parcela_com_auth_action") as span:
        if not apolice or not str(apolice).strip():
            return ActionFailure(message="Parâmetro 'apolice' é obrigatório", code="MISSING_APOLICE")

        token_res = _garantir_token_valido()
        if isinstance(token_res, ActionFailure):
            return token_res

        token = token_res.data.get("token") if hasattr(token_res, "data") else None
        if not token:
            return ActionFailure(message="Token não disponível", code="TOKEN_MISSING")

        return _chamar_financeiro(token=token, apolice=apolice)

# ======================================================================================
# TESTE SIMPLES (para debug/desenvolvimento)
# ======================================================================================

if __name__ == "__main__":
    # Mock das dependências para teste
    class MockActionSpan:
        def __init__(self, name):
            self.name = name
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def add_tags(self, tags):
            print(f"[SPAN] {self.name}: {tags}")
        def record_exception(self, e):
            print(f"[SPAN] {self.name} EXCEPTION: {e}")

    class MockActionResult:
        def __init__(self, success, message, code=None, data=None):
            self.success = success
            self.message = message
            self.code = code
            self.data = data or {}

    class MockActionSuccess(MockActionResult):
        def __init__(self, message, data=None):
            super().__init__(True, message, data=data)

    class MockActionFailure(MockActionResult):
        def __init__(self, message, code, data=None):
            super().__init__(False, message, code, data=data)

    class MockMemory:
        def __init__(self):
            self.data = {}
        def get(self, key):
            return self.data.get(key)
        def set(self, key, value):
            self.data[key] = value

    # Substituir as dependências por mocks
    ActionSpan = MockActionSpan
    ActionSuccess = MockActionSuccess
    ActionFailure = MockActionFailure
    
    # Mock simples de memória
    _memory = MockMemory()
    def get_session_memory(key):
        return _memory.get(key)
    def set_session_memory(key, value):
        _memory.set(key, value)

    print("=== TESTE DA ACTION ===")
    print(f"Parâmetro: apolice = 10531297990333")
    print()
    
    try:
        result = consulta_parcela_com_auth_action(apolice="10531297990333")
        print(f"RESULTADO: {result.message}")
        if hasattr(result, 'data'):
            print(f"DADOS: {result.data}")
        if hasattr(result, 'code'):
            print(f"CÓDIGO: {result.code}")
    except Exception as e:
        print(f"ERRO NO TESTE: {e}")
        import traceback
        traceback.print_exc()