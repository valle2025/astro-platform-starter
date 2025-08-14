from typing import Any, Dict, Optional
import time
import base64
import httpx

from tech4ai.actions.sdk.action_span import ActionSpan
from tech4ai.actions.sdk.response_objects import ActionSuccess, ActionFailure, ActionResult
from tech4ai.actions.sdk.memory_management import get_session_memory, set_session_memory

# ======================================================================================
# CONFIG INTERNA (ajuste se precisar)
# ======================================================================================

# Endpoint de OAuth (client_credentials com Basic Auth)
AUTH_URL = "https://portoapi-hml.portoseguro.com.br/oauth/v2/access-token"
AUTH_USERNAME = "cd49436f-2074-4c47-8546-c403e4a4d4a6"  # client_id
AUTH_PASSWORD = "a5a49c7a-1a9b-49c5-b118-8ce34e7dbf28"  # client_secret
AUTH_GRANT_TYPE = "client_credentials"
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
            # Basic Auth: base64(client_id:client_secret)
            credentials = f"{AUTH_USERNAME}:{AUTH_PASSWORD}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Authorization": f"Basic {encoded_credentials}",
            }
            data = {
                "grant_type": AUTH_GRANT_TYPE,  # client_credentials
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
                    data=payload,
                )

            token = payload.get("access_token")
            expires_in = payload.get("expires_in")

            if not token:
                return ActionFailure(
                    message="Campo 'access_token' ausente na resposta de auth",
                    code="TOKEN_MISSING",
                    data=payload,
                )

            now = int(time.time())
            expires_at = now + (int(expires_in) - 30 if isinstance(expires_in, int) and expires_in > 0 else 600)

            set_session_memory(MEM_TOKEN_KEY, token)
            set_session_memory(MEM_EXPIRES_AT_KEY, expires_at)

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

def _processar_resposta_financeira(payload):
    """
    Processa a resposta da API financeira para formato mais amigável
    - Formata Montante em R$
    - Formata DataVencimentoLiquido
    - Agrupa por ChaveAgrupamento
    """
    if not payload or 'Dados' not in payload:
        return payload

    dados = payload['Dados']

    # Processar e agrupar parcelas
    parcelas_processadas = []
    for parcela in dados:
        # Formatar data (YYYYMMDD -> DD/MM/YYYY)
        data_vencimento = parcela.get('DataVencimentoLiquido', '')
        data_formatada = ''
        if data_vencimento and data_vencimento != '00000000':
            try:
                data_formatada = f"{data_vencimento[6:8]}/{data_vencimento[4:6]}/{data_vencimento[0:4]}"
            except:
                data_formatada = data_vencimento

        # Formatar valor (string -> R$ X,XX)
        montante_str = parcela.get('Montante', '0')
        try:
            montante_float = float(montante_str)
            montante_formatado = f"R$ {montante_float:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        except:
            montante_formatado = f"R$ {montante_str}"

        parcela_processada = {
            "chave_agrupamento": parcela.get('ChaveAgrupamento', ''),
            "montante": montante_formatado,
            "data_vencimento": data_formatada,
            "data_vencimento_original": data_vencimento,
            "montante_original": montante_str,
            "numero_boleto": parcela.get('NumeroBoleto', ''),
            "situacao_parcela": parcela.get('SituacaoParcela', ''),
            "empresa": parcela.get('Empresa', ''),
            "codigo_susep": parcela.get('CodigoSusep', ''),
            "tipo_contrato": parcela.get('TipoContrato', ''),
            "codigo_tipo_produto": parcela.get('CodigoTipoProduto', ''),
            "numero_documento": parcela.get('NumeroDocumento', ''),
            "vigencia_de": parcela.get('VigenciaDe', ''),
            "vigencia_ate": parcela.get('VigenciaAte', ''),
            "forma_pagamento": parcela.get('FormaPagamento', ''),
            "moeda_transacao": parcela.get('MoedaTransacao', ''),
            "data_max_regularizacao": parcela.get('DataMaxRegularizacao', ''),
            "nome_pagador": parcela.get('NomePagador', ''),
            "cpf_cnpj_pagador": parcela.get('CpfCnpjPagador', ''),
            "codigo_mensagem": parcela.get('CodigoMensagem', ''),
            "texto_mensagem": parcela.get('TextoMensagem', ''),
            "permite_aviso_pagamento": parcela.get('PermiteAvisoPagamento', False)
        }

        parcelas_processadas.append(parcela_processada)

    # Ordenar por chave de agrupamento
    parcelas_processadas.sort(key=lambda x: x['chave_agrupamento'])

    # Calcular resumo
    try:
        total_montante = sum(float(p['montante_original']) for p in parcelas_processadas)
    except Exception:
        total_montante = 0.0

    return {
        "resumo": {
            "total_parcelas": len(parcelas_processadas),
            "valor_total": f"R$ {total_montante:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),
            "valor_total_numerico": total_montante,
            "ultima_atualizacao": payload.get('DataUltimaAtualizacao', ''),
            "hora_atualizacao": payload.get('HoraUltimaAtualizacao', '')
        },
        "parcelas": parcelas_processadas,
        "dados_originais": payload  # Manter dados originais para referência
    }

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
                # Processar a resposta para formato mais amigável
                dados_processados = _processar_resposta_financeira(payload)

                # SUCESSO: devolve os dados processados
                return ActionSuccess(
                    message="Consulta realizada com sucesso",
                    data=dados_processados,
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
    - Retorna os dados processados e formatados em caso de sucesso; e o payload bruto de erro em caso de falha.
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
# UTILITÁRIO DE TESTE (opcional)
# ======================================================================================

if __name__ == "__main__":
    # Exemplo rápido de teste
    apolice_exemplo = "10531297990333"
    res = consulta_parcela_com_auth_action(apolice=apolice_exemplo)
    if isinstance(res, ActionSuccess):
        resumo = res.data.get("resumo", {})
        print("✅ Sucesso na consulta")
        print(f"Total de parcelas: {resumo.get('total_parcelas')}")
        print(f"Valor total: {resumo.get('valor_total')}")
    else:
        print("❌ Falha na consulta")
        print(f"Código: {res.code}")
        print(f"Mensagem: {res.message}")
        if hasattr(res, "data"):
            print(f"Detalhes: {res.data}")