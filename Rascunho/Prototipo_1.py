from dataclasses import dataclass, field
from datetime import datetime
import heapq
from plyer import notification
from fastapi import FastAPI
from pydantic import BaseModel

# -----------------------------
# 1. MAPEAMENTOS DE PRIORIDADE
# -----------------------------
PRIORIDADE_CHAMADO = {
    'Server down': 1,
    'Impacta produção': 2,
    'Sem impacto': 3,
    'Dúvida': 4
}

PRIORIDADE_CLIENTE = {
    'Prioritário': 1,
    'Sem prioridade': 2,
    'Demonstração': 3
}

# -----------------------------
# 2. FUNÇÃO DE PRIORIDADE
# -----------------------------
def calcular_prioridade_combinada(tipo_chamado, tipo_cliente):
    return (
        PRIORIDADE_CHAMADO.get(tipo_chamado, 99),
        PRIORIDADE_CLIENTE.get(tipo_cliente, 99)
    )

# -----------------------------
# 3. FUNÇÃO DE NOTIFICAÇÃO
# -----------------------------
def enviar_notificacao_desktop(titulo: str, mensagem: str):
    notification.notify(
        title=titulo,
        message=mensagem,
        timeout=5
    )

# -----------------------------
# 4. ESTRUTURA DO CHAMADO
# -----------------------------
@dataclass(order=True)
class ChamadoSuporte:
    sort_index: tuple = field(init=False, repr=False)
    id_chamado: str
    cliente_nome: str
    tipo_cliente: str
    tipo_chamado: str
    descricao: str
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        self.sort_index = (
            PRIORIDADE_CHAMADO.get(self.tipo_chamado, 99),
            PRIORIDADE_CLIENTE.get(self.tipo_cliente, 99),
            self.timestamp
        )

# -----------------------------
# 5. FILA DE CHAMADOS
# -----------------------------
class FilaChamados:
    def __init__(self):
        self.heap = []

    def adicionar_chamado(self, chamado: ChamadoSuporte):
        prioridade_tuple = calcular_prioridade_combinada(chamado.tipo_chamado, chamado.tipo_cliente)
        item_heap = (prioridade_tuple, chamado.timestamp, chamado)
        heapq.heappush(self.heap, item_heap)

    def processar_proximo_chamado(self):
        if not self.heap:
            return None
        prioridade_tuple, _, chamado = heapq.heappop(self.heap)

        if prioridade_tuple[0] in [1, 2]:  # Server down ou Impacta produção
            enviar_notificacao_desktop(
                titulo="Chamado Urgente na Fila!",
                mensagem=(
                    f"Cliente: {chamado.cliente_nome} ({chamado.tipo_cliente})\n"
                    f"Tipo: {chamado.tipo_chamado}\n"
                    f"Descrição: {chamado.descricao[:50]}..."
                )
            )

        print(f"[PROCESSADO] {chamado.id_chamado} | {chamado.cliente_nome} | {chamado.tipo_chamado}")
        return chamado

# -----------------------------
# 6. API COM FASTAPI
# -----------------------------
app = FastAPI()
fila_chamados = FilaChamados()

class ChamadoRequest(BaseModel):
    id_chamado: str
    cliente_nome: str
    tipo_cliente: str
    tipo_chamado: str
    descricao: str

@app.post("/chamado")
def adicionar_chamado_api(dados: ChamadoRequest):
    chamado = ChamadoSuporte(
        id_chamado=dados.id_chamado,
        cliente_nome=dados.cliente_nome,
        tipo_cliente=dados.tipo_cliente,
        tipo_chamado=dados.tipo_chamado,
        descricao=dados.descricao
    )
    fila_chamados.adicionar_chamado(chamado)
    return {"mensagem": "Chamado adicionado com sucesso"}

@app.get("/proximo_chamado")
def processar_chamado_api():
    chamado = fila_chamados.processar_proximo_chamado()
    if chamado:
        return {"mensagem": "Chamado processado", "chamado": chamado.__dict__}
    return {"mensagem": "Nenhum chamado na fila"}