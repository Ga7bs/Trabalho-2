import heapq
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum
from flask import Flask, request, jsonify, render_template
from flask_sse import sse
from flask_socketio import SocketIO, emit
from plyer import notification

app = Flask(__name__)
app.config["SECRET_KEY"] = "secret!"
app.config["REDIS_URL"] = "redis://localhost"
app.register_blueprint(sse, url_prefix='/stream')
socketio = SocketIO(app)

# Enums para tipos estruturados
class TipoChamado(Enum):
    SERVER_DOWN = "Server down"
    IMPACTA_PRODUCAO = "Impacta produção"
    SEM_IMPACTO = "Sem impacto"
    DUVIDA = "Dúvida"

class TipoCliente(Enum):
    PRIORITARIO = "Prioritário"
    SEM_PRIORIDADE = "Sem prioridade"
    DEMONSTRACAO = "Demonstração"

class StatusChamado(Enum):
    PENDENTE = "Pendente"
    EM_ATENDIMENTO = "Em atendimento"
    RESOLVIDO = "Resolvido"

# Prioridades e tempos de resolução
PRIORIDADE_CHAMADO = {
    TipoChamado.SERVER_DOWN: 1,
    TipoChamado.IMPACTA_PRODUCAO: 2,
    TipoChamado.SEM_IMPACTO: 3,
    TipoChamado.DUVIDA: 4
}

PRIORIDADE_CLIENTE = {
    TipoCliente.PRIORITARIO: 1,
    TipoCliente.SEM_PRIORIDADE: 2,
    TipoCliente.DEMONSTRACAO: 3
}

TEMPO_RESOLUCAO = {
    TipoChamado.SERVER_DOWN: 120,
    TipoChamado.IMPACTA_PRODUCAO: 60,
    TipoChamado.SEM_IMPACTO: 30,
    TipoChamado.DUVIDA: 15
}

@dataclass
class AgenteSuporte:
    id: str
    nome: str
    especialidades: List[TipoChamado]
    chamado_atual: Optional[str] = None

@dataclass(order=True)
class ChamadoSuporte:
    id_chamado: str
    cliente_nome: str
    tipo_cliente: TipoCliente
    tipo_chamado: TipoChamado
    descricao: str
    status: StatusChamado = StatusChamado.PENDENTE
    timestamp: datetime = field(default_factory=datetime.now)
    prioridade_manual: Optional[int] = None
    agente_atribuido: Optional[str] = None
    tempo_estimado: timedelta = field(init=False)

    def __post_init__(self):
        self.tempo_estimado = timedelta(minutes=TEMPO_RESOLUCAO[self.tipo_chamado])

    def prioridade_combinada(self) -> tuple:
        """Calcula a prioridade considerando a manual se existir"""
        prioridade_chamado = self.prioridade_manual or PRIORIDADE_CHAMADO[self.tipo_chamado]
        prioridade_cliente = PRIORIDADE_CLIENTE[self.tipo_cliente]
        return (prioridade_chamado, prioridade_cliente)

class SistemaChamados:
    def __init__(self):
        self.fila = []
        self.contador = 0
        self.agentes: Dict[str, AgenteSuporte] = {}
        self.chamados_ativos: Dict[str, ChamadoSuporte] = {}
        self.ultimo_id = 0
        self.chamados_em_atendimento: Dict[str, ChamadoSuporte] = {}

    def _gerar_id(self) -> str:
        self.ultimo_id += 1
        return f"INC-{self.ultimo_id}"

    def adicionar_agente(self, agente: AgenteSuporte):
        self.agentes[agente.id] = agente

    def adicionar_chamado(self, dados_chamado: dict) -> Optional[ChamadoSuporte]:
        try:
            if 'id_chamado' not in dados_chamado or not dados_chamado['id_chamado']:
                dados_chamado['id_chamado'] = self._gerar_id()

            chamado = ChamadoSuporte(
                id_chamado=dados_chamado['id_chamado'],
                cliente_nome=dados_chamado['cliente_nome'],
                tipo_cliente=TipoCliente(dados_chamado['tipo_cliente']),
                tipo_chamado=TipoChamado(dados_chamado['tipo_chamado']),
                descricao=dados_chamado['descricao'],
                prioridade_manual=dados_chamado.get('prioridade_manual')
            )
            
            heapq.heappush(
                self.fila,
                (chamado.prioridade_combinada(), chamado.timestamp, self.contador, chamado)
            )
            self.contador += 1
            self.chamados_ativos[chamado.id_chamado] = chamado
            
            # Notificação automática para alta prioridade
            if chamado.prioridade_combinada()[0] <= 2:
                self._enviar_notificacao(
                    titulo="Novo Chamado Urgente!",
                    mensagem=f"Cliente: {chamado.cliente_nome}\nTipo: {chamado.tipo_chamado.value}"
                )
            
            self._notificar_mudanca()
            return chamado
        except (KeyError, ValueError) as e:
            print(f"Erro ao adicionar chamado: {e}")
            return None

    def escalar_chamado(self, id_chamado: str, nova_prioridade: int) -> bool:
        if id_chamado not in self.chamados_ativos:
            return False
        
        chamado = self.chamados_ativos[id_chamado]
        chamado.prioridade_manual = nova_prioridade
        
        # Reconstruir a fila com a nova prioridade
        self.fila = [
            (c.prioridade_combinada(), c.timestamp, i, c) 
            for i, (_, _, _, c) in enumerate(self.fila)
        ]
        heapq.heapify(self.fila)
        
        # Notificar sobre a mudança de prioridade
        self._enviar_notificacao(
            titulo="Chamado Escalado!",
            mensagem=f"Chamado {id_chamado} agora tem prioridade {nova_prioridade}"
        )
        
        self._notificar_mudanca()
        return True

    def atribuir_agente(self, id_chamado: str, id_agente: str) -> bool:
        if id_chamado not in self.chamados_ativos or id_agente not in self.agentes:
            return False
        
        chamado = self.chamados_ativos[id_chamado]
        agente = self.agentes[id_agente]
        
        # Liberar agente atual se estiver ocupado
        if agente.chamado_atual:
            self.chamados_ativos[agente.chamado_atual].agente_atribuido = None
            self.chamados_ativos[agente.chamado_atual].status = StatusChamado.PENDENTE
        
        chamado.agente_atribuido = id_agente
        chamado.status = StatusChamado.EM_ATENDIMENTO
        agente.chamado_atual = id_chamado
        
        # Mover para a lista de em atendimento
        self.chamados_em_atendimento[id_chamado] = chamado
        
        self._notificar_mudanca()
        return True

    def processar_proximo_chamado(self) -> Optional[ChamadoSuporte]:
        if not self.fila:
            return None

        _, _, _, chamado = heapq.heappop(self.fila)
        chamado.status = StatusChamado.EM_ATENDIMENTO
        
        # Atribuir automaticamente a um agente disponível
        agente_disponivel = next(
            (a for a in self.agentes.values() 
             if not a.chamado_atual and chamado.tipo_chamado in a.especialidades),
            None
        )
        
        if agente_disponivel:
            self.atribuir_agente(chamado.id_chamado, agente_disponivel.id)
        else:
            self.chamados_em_atendimento[chamado.id_chamado] = chamado
        
        # Notificação para chamados urgentes
        if chamado.prioridade_combinada()[0] <= 2:
            self._enviar_notificacao(
                titulo="Chamado Urgente em Atendimento!",
                mensagem=f"Cliente: {chamado.cliente_nome}\nTipo: {chamado.tipo_chamado.value}"
            )
        
        self._notificar_mudanca()
        return chamado

    def finalizar_chamado(self, id_chamado: str) -> bool:
        """Finaliza um chamado e atribui automaticamente o próximo ao agente"""
        if id_chamado not in self.chamados_em_atendimento:
            return False

        chamado = self.chamados_em_atendimento.pop(id_chamado)
        agente_id = chamado.agente_atribuido
        chamado.status = StatusChamado.RESOLVIDO
        
        # Remover dos ativos
        if id_chamado in self.chamados_ativos:
            del self.chamados_ativos[id_chamado]
        
        # Se houver agente vinculado
        if agente_id and agente_id in self.agentes:
            agente = self.agentes[agente_id]
            agente.chamado_atual = None
            
            # Tentar atribuir o próximo chamado da fila ao agente
            self._atribuir_proximo_chamado(agente_id)
        
        self._notificar_mudanca()
        return True

    def _atribuir_proximo_chamado(self, id_agente: str) -> bool:
        """Atribui o próximo chamado compatível ao agente"""
        agente = self.agentes[id_agente]
        
        # Verificar se há chamados na fila
        if not self.fila:
            return False
            
        # Pegar o próximo chamado (já está ordenado por prioridade)
        _, _, _, proximo_chamado = heapq.heappop(self.fila)
        
        # Verificar compatibilidade
        if proximo_chamado.tipo_chamado in agente.especialidades:
            # Atribuir ao agente
            proximo_chamado.agente_atribuido = id_agente
            proximo_chamado.status = StatusChamado.EM_ATENDIMENTO
            agente.chamado_atual = proximo_chamado.id_chamado
            self.chamados_em_atendimento[proximo_chamado.id_chamado] = proximo_chamado
            
            # Atualizar na lista de ativos
            self.chamados_ativos[proximo_chamado.id_chamado] = proximo_chamado
            
            # Notificação
            if proximo_chamado.prioridade_combinada()[0] <= 2:
                self._enviar_notificacao(
                    titulo="Atribuição Automática",
                    mensagem=f"{agente.nome} assumiu {proximo_chamado.id_chamado}"
                )
            return True
        else:
            # Se não for compatível, recolocar na fila
            heapq.heappush(self.fila, (
                proximo_chamado.prioridade_combinada(),
                proximo_chamado.timestamp,
                self.contador,
                proximo_chamado
            ))
            self.contador += 1
            return False
        
        # Remover dos ativos
        if id_chamado in self.chamados_ativos:
            del self.chamados_ativos[id_chamado]
        
        # Liberar o agente
        if agente_id and agente_id in self.agentes:
            self.agentes[agente_id].chamado_atual = None
            
            # Atribuir automaticamente o próximo chamado compatível ao agente liberado
            self._atribuir_proximo_chamado(agente_id)
        
        self._notificar_mudanca()
        return True

    def _atribuir_proximo_chamado(self, id_agente: str) -> bool:
        """Tenta atribuir automaticamente um novo chamado ao agente"""
        agente = self.agentes[id_agente]
        
        # Encontrar o próximo chamado compatível com as especialidades do agente
        for i, (_, _, _, chamado) in enumerate(self.fila):
            if (chamado.status == StatusChamado.PENDENTE and 
                chamado.tipo_chamado in agente.especialidades):
                
                # Remove da fila
                heapq.heappop(self.fila)
                
                # Atribui ao agente
                chamado.agente_atribuido = id_agente
                chamado.status = StatusChamado.EM_ATENDIMENTO
                agente.chamado_atual = chamado.id_chamado
                self.chamados_em_atendimento[chamado.id_chamado] = chamado
                
                # Notificação para chamados urgentes
                if chamado.prioridade_combinada()[0] <= 2:
                    self._enviar_notificacao(
                        titulo="Novo Chamado Atribuído!",
                        mensagem=f"Agente {agente.nome} assumiu chamado urgente"
                    )
                
                return True
        return False
        
        # Liberar o agente
        if chamado.agente_atribuido and chamado.agente_atribuido in self.agentes:
            self.agentes[chamado.agente_atribuido].chamado_atual = None
        
        # Remover dos ativos
        if id_chamado in self.chamados_ativos:
            del self.chamados_ativos[id_chamado]
        
        self._notificar_mudanca()
        return True

    def _notificar_mudanca(self):
        """Notifica todas as interfaces conectadas sobre mudanças"""
        socketio.emit('atualizar_fila', {
            'fila': [self._serializar_chamado(c) for _, _, _, c in self.fila],
            'agentes': [self._serializar_agente(a) for a in self.agentes.values()],
            'chamados_ativos': [self._serializar_chamado(c) for c in self.chamados_ativos.values()],
            'chamados_em_atendimento': [self._serializar_chamado(c) for c in self.chamados_em_atendimento.values()]
        })

    def _serializar_chamado(self, chamado: ChamadoSuporte) -> dict:
        return {
            "id": chamado.id_chamado,
            "cliente": chamado.cliente_nome,
            "tipo_chamado": chamado.tipo_chamado.value,
            "tipo_cliente": chamado.tipo_cliente.value,
            "prioridade": chamado.prioridade_combinada(),
            "tempo_estimado": str(chamado.tempo_estimado),
            "agente": chamado.agente_atribuido,
            "status": chamado.status.value,
            "descricao": chamado.descricao,
            "timestamp": chamado.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }

    def _serializar_agente(self, agente: AgenteSuporte) -> dict:
        return {
            "id": agente.id,
            "nome": agente.nome,
            "chamado_atual": agente.chamado_atual,
            "especialidades": [e.value for e in agente.especialidades]
        }

    @staticmethod
    def _enviar_notificacao(titulo: str, mensagem: str):
        try:
            notification.notify(
                title=titulo,
                message=mensagem,
                app_name="Sistema de Chamados",
                timeout=10
            )
        except Exception as e:
            print(f"Erro ao enviar notificação: {e}")

# Configuração inicial do sistema
sistema = SistemaChamados()
sistema.adicionar_agente(AgenteSuporte(
    id="ag1",
    nome="Ana Silva",
    especialidades=[TipoChamado.SERVER_DOWN, TipoChamado.IMPACTA_PRODUCAO]
))
sistema.adicionar_agente(AgenteSuporte(
    id="ag2",
    nome="Carlos Souza",
    especialidades=[TipoChamado.SEM_IMPACTO, TipoChamado.DUVIDA]
))

# Rotas da API
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/chamados', methods=['GET', 'POST'])
def api_chamados():
    if request.method == 'POST':
        dados = request.json
        chamado = sistema.adicionar_chamado(dados)
        if chamado:
            return jsonify(sistema._serializar_chamado(chamado)), 201
        return jsonify({"erro": "Dados inválidos"}), 400
    else:
        return jsonify({
            "fila": [sistema._serializar_chamado(c) for _, _, _, c in sistema.fila],
            "agentes": [sistema._serializar_agente(a) for a in sistema.agentes.values()],
            "chamados_em_atendimento": [sistema._serializar_chamado(c) for c in sistema.chamados_em_atendimento.values()]
        })

@app.route('/api/chamados/<id_chamado>/escalar', methods=['PUT'])
def api_escalar_chamado(id_chamado):
    nova_prioridade = request.json.get('prioridade')
    if sistema.escalar_chamado(id_chamado, nova_prioridade):
        return jsonify({"status": "sucesso"})
    return jsonify({"erro": "Chamado não encontrado"}), 404

@app.route('/api/chamados/<id_chamado>/atribuir', methods=['PUT'])
def api_atribuir_chamado(id_chamado):
    id_agente = request.json.get('id_agente')
    if sistema.atribuir_agente(id_chamado, id_agente):
        return jsonify({"status": "sucesso"})
    return jsonify({"erro": "Chamado ou agente não encontrado"}), 404

@app.route('/api/chamados/proximo', methods=['POST'])
def api_processar_chamado():
    chamado = sistema.processar_proximo_chamado()
    if chamado:
        return jsonify(sistema._serializar_chamado(chamado))
    return jsonify({"erro": "Fila vazia"}), 404

@app.route('/api/chamados/<id_chamado>/finalizar', methods=['POST'])
def api_finalizar_chamado(id_chamado):
    if sistema.finalizar_chamado(id_chamado):
        return jsonify({"status": "sucesso"})
    return jsonify({"erro": "Chamado não encontrado ou não está em atendimento"}), 404

# WebSocket events
@socketio.on('connect')
def handle_connect():
    emit('atualizar_fila', {
        'fila': [sistema._serializar_chamado(c) for _, _, _, c in sistema.fila],
        'agentes': [sistema._serializar_agente(a) for a in sistema.agentes.values()],
        'chamados_em_atendimento': [sistema._serializar_chamado(c) for c in sistema.chamados_em_atendimento.values()]
    })

@socketio.on('novo_chamado')
def handle_novo_chamado(data):
    sistema.adicionar_chamado(data)

@socketio.on('escalar_chamado')
def handle_escalar_chamado(data):
    sistema.escalar_chamado(data['id_chamado'], data['prioridade'])

@socketio.on('finalizar_chamado')
def handle_finalizar_chamado(data):
    sistema.finalizar_chamado(data['id_chamado'])

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0')