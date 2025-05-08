import heapq
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import threading
import time
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO
from plyer import notification
import logging
from enum import Enum
from typing import Dict, List, Optional

# --- Configuração de Log ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler('suporte.log')]
)
logger = logging.getLogger(__name__)

# --- CONSTANTES ---
NOTIFICAR_CHAMADOS_CRITICOS = True
TEMPO_VERIFICACAO_ATENDIMENTO = 10  # segundos
LIMITE_DESCRICAO_NOTIFICACAO = 50  # caracteres

# --- PRIORIDADES ---
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

# --- TEMPO MÉDIO DE RESOLUÇÃO ---
TEMPO_RESOLUCAO = {
    'Server down': 120,
    'Impacta produção': 60,
    'Sem impacto': 30,
    'Dúvida': 15
}

# --- AGENTES DE SUPORTE ---
AGENTES = {
    'agente1': 'Ana Silva',
    'agente2': 'Carlos Souza',
    'agente3': 'Mariana Lima'
}

# --- ESTRUTURAS DE DADOS ---
class StatusChamado(Enum):
    PENDENTE = "Pendente"
    EM_ATENDIMENTO = "Em Atendimento"
    RESOLVIDO = "Resolvido"

@dataclass
class ChamadoSuporte:
    id_chamado: str
    cliente_nome: str
    tipo_cliente: str
    tipo_chamado: str
    descricao: str
    timestamp: datetime = field(default_factory=datetime.now)
    status: StatusChamado = StatusChamado.PENDENTE
    agente: Optional[str] = None
    tempo_estimado: timedelta = field(init=False)

    def __post_init__(self):
        if self.tipo_cliente not in PRIORIDADE_CLIENTE:
            raise ValueError(f"Tipo de cliente inválido: {self.tipo_cliente}")
        if self.tipo_chamado not in PRIORIDADE_CHAMADO:
            raise ValueError(f"Tipo de chamado inválido: {self.tipo_chamado}")
        self.tempo_estimado = timedelta(minutes=TEMPO_RESOLUCAO[self.tipo_chamado])

# --- MÓDULO DE NOTIFICAÇÃO ---
def enviar_notificacao_desktop(titulo: str, mensagem: str) -> bool:
    """Envia notificação para a área de trabalho."""
    try:
        notification.notify(
            title=titulo,
            message=mensagem,
            app_name='Sistema de Suporte',
            timeout=10
        )
        logger.info(f"Notificação enviada: {titulo}")
        return True
    except Exception as e:
        logger.error(f"Falha ao enviar notificação: {e}")
        return False

# --- SISTEMA DE FILA DE PRIORIDADES ---
class SistemaChamados:
    def __init__(self):
        self._fila = []
        self._lock = threading.Lock()
        self._contador = 0
        self._id_map: Dict[str, ChamadoSuporte] = {}
        self._chamados_em_atendimento: Dict[str, ChamadoSuporte] = {}

    def adicionar_chamado(self, dados_chamado: dict) -> ChamadoSuporte:
        """Adiciona um chamado à fila de prioridades (O(log n))."""
        try:
            id_chamado = f"CHAM-{int(datetime.now().timestamp())}-{self._contador}"
            chamado = ChamadoSuporte(
                id_chamado=id_chamado,
                cliente_nome=dados_chamado['cliente_nome'],
                tipo_cliente=dados_chamado['tipo_cliente'],
                tipo_chamado=dados_chamado['tipo_chamado'],
                descricao=dados_chamado['descricao']
            )
            
            prioridade = self._calcular_prioridade_combinada(chamado)
            
            with self._lock:
                # Mantém o novo chamado na fila
                heapq.heappush(self._fila, (prioridade, chamado.timestamp, chamado))
                self._contador += 1
                self._id_map[chamado.id_chamado] = chamado
                self._notificar_mudanca_fila()
                logger.info(f"Chamado {chamado.id_chamado} adicionado à fila")
            
            return chamado
        except KeyError as e:
            raise ValueError(f"Campo faltando: {str(e)}")

    def _calcular_prioridade_combinada(self, chamado: ChamadoSuporte) -> tuple:
        """Retorna (prioridade_chamado, prioridade_cliente)."""
        return (PRIORIDADE_CHAMADO[chamado.tipo_chamado], PRIORIDADE_CLIENTE[chamado.tipo_cliente])

    def escalonar_chamado(self, id_chamado: str, nova_prioridade: int) -> bool:
        """Aumenta manualmente a prioridade de um chamado (O(n))."""
        with self._lock:
            if id_chamado not in self._id_map:
                return False
                
            chamado = self._id_map[id_chamado]
            nova_prioridade_tuple = (nova_prioridade, PRIORIDADE_CLIENTE[chamado.tipo_cliente])
            
            # Reconstruir a fila com a nova prioridade
            nova_fila = []
            for item in self._fila:
                _, timestamp, item_chamado = item
                if item_chamado.id_chamado == id_chamado:
                    heapq.heappush(nova_fila, (nova_prioridade_tuple, timestamp, chamado))
                else:
                    heapq.heappush(nova_fila, item)
            
            self._fila = nova_fila
            self._notificar_mudanca_fila()
            logger.info(f"Chamado {id_chamado} escalonado para prioridade {nova_prioridade}")
            return True

    def atribuir_agente(self, id_chamado: str, agente_id: str) -> bool:
        """Atribui um agente a um chamado."""
        with self._lock:
            if id_chamado not in self._id_map or agente_id not in AGENTES:
                return False
            
            chamado = self._id_map[id_chamado]
            chamado.agente = agente_id
            chamado.status = StatusChamado.EM_ATENDIMENTO
            
            # Mover o chamado para atendimentos em andamento
            self._chamados_em_atendimento[id_chamado] = chamado
            
            self._notificar_mudanca_fila()
            logger.info(f"Chamado {id_chamado} atribuído a {AGENTES[agente_id]}")
            return True

    def processar_proximo_chamado(self) -> Optional[ChamadoSuporte]:
        """Processa o próximo chamado (O(log n))."""
        with self._lock:
            if not self._fila:
                return None

            prioridade, timestamp, chamado = heapq.heappop(self._fila)
            chamado.status = StatusChamado.EM_ATENDIMENTO
            
            # Armazena o chamado em atendimento
            self._chamados_em_atendimento[chamado.id_chamado] = chamado
            
            # Remove do índice principal
            self._id_map.pop(chamado.id_chamado, None)
            self._notificar_mudanca_fila()

        logger.info(f"Processando chamado {chamado.id_chamado}")

        if NOTIFICAR_CHAMADOS_CRITICOS and prioridade[0] <= 2:
            self._notificar_chamado_critico(chamado)

        return chamado

    def _notificar_chamado_critico(self, chamado: ChamadoSuporte):
        """Envia notificação para chamados críticos."""
        titulo = "Chamado Urgente na Fila!"
        mensagem = (
            f"Cliente: {chamado.cliente_nome}\n"
            f"Tipo: {chamado.tipo_chamado}\n"
            f"Descrição: {chamado.descricao[:LIMITE_DESCRICAO_NOTIFICACAO]}..."
        )
        enviar_notificacao_desktop(titulo, mensagem)

    def _notificar_mudanca_fila(self):
        """Notifica mudanças na fila via WebSocket."""
        socketio.emit('atualizar_fila', {
            'fila': self._serializar_fila(),
            'em_atendimento': self._serializar_em_atendimento()
        })

    def _serializar_fila(self) -> List[dict]:
        """Serializa a fila para JSON."""
        return [{
            'id': chamado.id_chamado,
            'cliente': chamado.cliente_nome,
            'tipo': chamado.tipo_chamado,
            'prioridade': self._calcular_prioridade_combinada(chamado)[0],
            'tempo_estimado': str(chamado.tempo_estimado)
        } for _, _, chamado in self._fila]

    def _serializar_em_atendimento(self) -> List[dict]:
        """Serializa chamados em atendimento."""
        return [{
            'id': chamado.id_chamado,
            'agente': AGENTES[chamado.agente] if chamado.agente else "Não atribuído",
            'tempo_estimado': str(chamado.tempo_estimado)
        } for chamado in self._chamados_em_atendimento.values()]

    @property
    def tamanho(self) -> int:
        """Retorna o tamanho atual da fila (O(1))."""
        with self._lock:
            return len(self._fila)

# --- API WEB (FLASK + WEBSOCKET) ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")
sistema = SistemaChamados()

# --- ROTAS DA API ---
@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/chamado', methods=['POST'])
def api_adicionar_chamado():
    """Adiciona um novo chamado via API."""
    try:
        dados = request.json
        chamado = sistema.adicionar_chamado(dados)
        return jsonify({
            "status": "success",
            "id_chamado": chamado.id_chamado,
            "prioridade": sistema._calcular_prioridade_combinada(chamado)[0],
            "tempo_estimado": str(chamado.tempo_estimado)
        }), 201
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/chamado/<id_chamado>/escalonar', methods=['POST'])
def api_escalonar_chamado(id_chamado):
    """Escalona um chamado para prioridade máxima."""
    if sistema.escalonar_chamado(id_chamado, 1):  # Prioridade 1 = Server down
        return jsonify({"status": "success"}), 200
    return jsonify({"status": "error", "message": "Chamado não encontrado"}), 404

@app.route('/chamado/<id_chamado>/atribuir', methods=['POST'])
def api_atribuir_agente(id_chamado):
    """Atribui um agente a um chamado."""
    agente_id = request.json.get('agente_id')
    if sistema.atribuir_agente(id_chamado, agente_id):
        return jsonify({"status": "success"}), 200
    return jsonify({"status": "error"}), 400

@app.route('/proximo_chamado', methods=['GET'])
def api_processar_chamado():
    """Processa o próximo chamado manualmente."""
    chamado = sistema.processar_proximo_chamado()
    if not chamado:
        return jsonify({"status": "empty"}), 404
    return jsonify({
        "id_chamado": chamado.id_chamado,
        "prioridade": sistema._calcular_prioridade_combinada(chamado)[0],
        "tempo_estimado": str(chamado.tempo_estimado)
    }), 200

# --- WEBSOCKETS ---
@socketio.on('connect')
def handle_connect():
    """Envia o estado atual ao conectar."""
    socketio.emit('atualizar_fila', {
        'fila': sistema._serializar_fila(),
        'em_atendimento': sistema._serializar_em_atendimento()
    })

# --- PROCESSAMENTO AUTOMÁTICO ---
def processar_chamados_continuamente():
    """Processa chamados a cada 5 segundos, se houver chamados na fila."""
    while True:
        time.sleep(TEMPO_VERIFICACAO_ATENDIMENTO)
        sistema.processar_proximo_chamado()  # Processa o próximo chamado na fila

# --- INICIALIZAÇÃO ---
def iniciar_sistema():
    threading.Thread(
        target=processar_chamados_continuamente,
        daemon=True
    ).start()

    # Exemplos iniciais
    sistema.adicionar_chamado({
        "cliente_nome": "Empresa A",
        "tipo_cliente": "Prioritário",
        "tipo_chamado": "Server down",
        "descricao": "Servidor fora do ar"
    })
    
    logger.info("Sistema iniciado")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

if __name__ == '__main__':
    iniciar_sistema()
