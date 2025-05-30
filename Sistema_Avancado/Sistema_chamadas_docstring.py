import heapq  # Estrutura de dados para filas de prioridade
import time  # Usado para medições de tempo e delays
from datetime import datetime, timedelta  # Manipulação de datas e tempos
from dataclasses import dataclass, field  # Para definição de classes simples com menos boilerplate
from typing import Optional, List, Dict  # Anotações de tipo de dados
from enum import Enum  # Definição de enums para tipos estruturados
from flask import Flask, request, jsonify, render_template  # Framework web e utilitários de requisição/resposta
from flask_sse import sse  # Server-Sent Events para notificações em tempo real via HTTP
from flask_socketio import SocketIO, emit  # WebSockets para comunicação em tempo real
from plyer import notification  # Notificações no desktop

# Inicializa a aplicação Flask
app = Flask(__name__)
app.config["SECRET_KEY"] = "secret!"  # Chave de segurança para sessões e assinaturas
app.config["REDIS_URL"] = "redis://localhost"  # URL do Redis para o Flask-SSE
app.register_blueprint(sse, url_prefix='/stream')  # Registra o blueprint de SSE sob /stream
socketio = SocketIO(app)  # Inicializa o SocketIO para WebSockets

# ----- Definição de Enums para tipos de chamado, cliente e status -----
class TipoChamado(Enum):
    """
    Enumeração dos tipos de chamados suportados.
    SERVER_DOWN: Indica que o servidor está indisponível.
    IMPACTA_PRODUCAO: Impacto direto na produção.
    SEM_IMPACTO: Sem impacto imediato.
    DUVIDA: Chamado para esclarecer dúvidas.
    """
    SERVER_DOWN = "Server down"
    IMPACTA_PRODUCAO = "Impacta produção"
    SEM_IMPACTO = "Sem impacto"
    DUVIDA = "Dúvida"

class TipoCliente(Enum):
    """
    Enumeração dos tipos de cliente.
    PRIORITARIO: Clientes com prioridade alta.
    SEM_PRIORIDADE: Clientes sem prioridade especial.
    DEMONSTRACAO: Chamados de demonstração.
    """
    PRIORITARIO = "Prioritário"
    SEM_PRIORIDADE = "Sem prioridade"
    DEMONSTRACAO = "Demonstração"

class StatusChamado(Enum):
    """
    Enumeração dos possíveis status de um chamado.
    PENDENTE: Aguardando atendimento.
    EM_ATENDIMENTO: Em atendimento por um agente.
    RESOLVIDO: Chamado finalizado.
    """
    PENDENTE = "Pendente"
    EM_ATENDIMENTO = "Em atendimento"
    RESOLVIDO = "Resolvido"

# ----- Mapeamentos de prioridade e tempo estimado de resolução -----
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

# Tempo em minutos para resolver cada tipo de chamado
TEMPO_RESOLUCAO = {
    TipoChamado.SERVER_DOWN: 120,
    TipoChamado.IMPACTA_PRODUCAO: 60,
    TipoChamado.SEM_IMPACTO: 30,
    TipoChamado.DUVIDA: 15
}

@dataclass
class AgenteSuporte:
    """
    Representa um agente de suporte com suas especialidades e chamado atual.
    :param id: Identificador único do agente.
    :param nome: Nome do agente.
    :param especialidades: Lista de tipos de chamado que o agente atende.
    :param chamado_atual: ID do chamado que o agente está atendendo (ou None).
    """
    id: str
    nome: str
    especialidades: List[TipoChamado]
    chamado_atual: Optional[str] = None

@dataclass(order=True)
class ChamadoSuporte:
    """
    Representa um chamado de suporte e sua lógica de prioridade.
    :param id_chamado: Identificador do chamado.
    :param cliente_nome: Nome do cliente que abriu o chamado.
    :param tipo_cliente: Tipo de cliente (prioritário, etc.).
    :param tipo_chamado: Tipo do chamado (server down, dúvida, etc.).
    :param descricao: Descrição do problema.
    """
    id_chamado: str
    cliente_nome: str
    tipo_cliente: TipoCliente
    tipo_chamado: TipoChamado
    descricao: str
    status: StatusChamado = StatusChamado.PENDENTE
    timestamp: datetime = field(default_factory=datetime.now)
    prioridade_manual: Optional[int] = None  # Prioridade ajustada manualmente
    agente_atribuido: Optional[str] = None  # ID do agente atribuído
    tempo_estimado: timedelta = field(init=False)

    def __post_init__(self):
        """
        Após a criação, calcula o tempo estimado de resolução com base no tipo de chamado.
        """
        self.tempo_estimado = timedelta(minutes=TEMPO_RESOLUCAO[self.tipo_chamado])

    def prioridade_combinada(self) -> tuple:
        """
        Combina a prioridade do chamado e do cliente em uma tupla para ordenação:
        (prioridade_chamado, prioridade_cliente)
        Menor valor tem prioridade maior.
        """
        prioridade_chamado = self.prioridade_manual or PRIORIDADE_CHAMADO[self.tipo_chamado]
        prioridade_cliente = PRIORIDADE_CLIENTE[self.tipo_cliente]
        return (prioridade_chamado, prioridade_cliente)

class SistemaChamados:
    """
    Sistema principal de gerenciamento de chamados:
    - Fila de prioridade
    - Atribuição e escalonamento
    - Notificações via SSE, SocketIO e desktop
    """
    def __init__(self):
        """
        Inicializa estruturas de dados para fila, agentes e chamados.
        """
        self.fila = []  # Heap de prioridade
        self.contador = 0  # Contador auxiliar para desempate em heap
        self.agentes: Dict[str, AgenteSuporte] = {}
        self.chamados_ativos: Dict[str, ChamadoSuporte] = {}
        self.ultimo_id = 0
        self.chamados_em_atendimento: Dict[str, ChamadoSuporte] = {}

    def _gerar_id(self) -> str:
        """
        Gera um novo ID sequencial para chamados (ex: INC-1, INC-2).
        """
        self.ultimo_id += 1
        return f"INC-{self.ultimo_id}"

    def adicionar_agente(self, agente: AgenteSuporte):
        """
        Adiciona um agente ao sistema.
        :param agente: Instância de AgenteSuporte.
        """
        self.agentes[agente.id] = agente

    def adicionar_chamado(self, dados_chamado: dict) -> Optional[ChamadoSuporte]:
        """
        Cria e enfileira um novo chamado a partir de dados JSON.
        Dispara notificações para chamados de alta prioridade.
        """
        try:
            # Gera ID se não fornecido
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
            # Insere no heap com chave de ordenação (prioridade, timestamp, contador)
            heapq.heappush(
                self.fila,
                (chamado.prioridade_combinada(), chamado.timestamp, self.contador, chamado)
            )
            self.contador += 1
            self.chamados_ativos[chamado.id_chamado] = chamado

            # Notificação desktop para prioridade alta (<=2)
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
        """
        Ajusta manualmente a prioridade de um chamado e reordena a fila.
        Envia notificação sobre a mudança.
        """
        if id_chamado not in self.chamados_ativos:
            return False
        chamado = self.chamados_ativos[id_chamado]
        chamado.prioridade_manual = nova_prioridade
        # Reconstrói fila com novas prioridades
        self.fila = [
            (c.prioridade_combinada(), c.timestamp, i, c)
            for i, (_, _, _, c) in enumerate(self.fila)
        ]
        heapq.heapify(self.fila)
        # Notifica escalonamento
        self._enviar_notificacao(
            titulo="Chamado Escalado!",
            mensagem=f"Chamado {id_chamado} agora tem prioridade {nova_prioridade}"
        )
        self._notificar_mudanca()
        return True

    def atribuir_agente(self, id_chamado: str, id_agente: str) -> bool:
        """
        Atribui um agente específico a um chamado.
        Se o agente já estiver ocupado, libera o chamado anterior.
        """
        if id_chamado not in self.chamados_ativos or id_agente not in self.agentes:
            return False
        chamado = self.chamados_ativos[id_chamado]
        agente = self.agentes[id_agente]
        # Libera agente de seu chamado atual, se houver
        if agente.chamado_atual:
            antigo = self.chamados_ativos[agente.chamado_atual]
            antigo.agente_atribuido = None
            antigo.status = StatusChamado.PENDENTE
        chamado.agente_atribuido = id_agente
        chamado.status = StatusChamado.EM_ATENDIMENTO
        agente.chamado_atual = id_chamado
        self.chamados_em_atendimento[id_chamado] = chamado
        self._notificar_mudanca()
        return True

    def processar_proximo_chamado(self) -> Optional[ChamadoSuporte]:
        """
        Remove e retorna o próximo chamado da fila, atribuindo a um agente disponível.
        Envia notificações se urgente.
        """
        if not self.fila:
            return None
        _, _, _, chamado = heapq.heappop(self.fila)
        chamado.status = StatusChamado.EM_ATENDIMENTO
        # Seleciona agente disponível com especialidade
        agente_disponivel = next(
            (a for a in self.agentes.values()
             if not a.chamado_atual and chamado.tipo_chamado in a.especialidades),
            None
        )
        if agente_disponivel:
            self.atribuir_agente(chamado.id_chamado, agente_disponivel.id)
        else:
            self.chamados_em_atendimento[chamado.id_chamado] = chamado
        if chamado.prioridade_combinada()[0] <= 2:
            self._enviar_notificacao(
                titulo="Chamado Urgente em Atendimento!",
                mensagem=f"Cliente: {chamado.cliente_nome}\nTipo: {chamado.tipo_chamado.value}"
            )
        self._notificar_mudanca()
        return chamado

    def finalizar_chamado(self, id_chamado: str) -> bool:
        """
        Finaliza um chamado em atendimento e tenta atribuir o próximo ao mesmo agente.
        """
        if id_chamado not in self.chamados_em_atendimento:
            return False
        chamado = self.chamados_em_atendimento.pop(id_chamado)
        agente_id = chamado.agente_atribuido
        chamado.status = StatusChamado.RESOLVIDO
        # Remove dos ativos
        del self.chamados_ativos[id_chamado]
        # Se havia agente, libera e atribui próximo
        if agente_id and agente_id in self.agentes:
            agente = self.agentes[agente_id]
            agente.chamado_atual = None
            self._atribuir_proximo_chamado(agente_id)
        self._notificar_mudanca()
        return True

    def _atribuir_proximo_chamado(self, id_agente: str) -> bool:
        """
        Atribui automaticamente o próximo chamado compatível com o agente.
        Percorre a fila procurando o primeiro compatível.
        """
        agente = self.agentes[id_agente]
        for i, (_, _, _, chamado) in enumerate(self.fila):
            if chamado.status == StatusChamado.PENDENTE and chamado.tipo_chamado in agente.especialidades:
                heapq.heappop(self.fila)
                chamado.agente_atribuido = id_agente
                chamado.status = StatusChamado.EM_ATENDIMENTO
                agente.chamado_atual = chamado.id_chamado
                self.chamados_em_atendimento[chamado.id_chamado] = chamado
                if chamado.prioridade_combinada()[0] <= 2:
                    self._enviar_notificacao(
                        titulo="Novo Chamado Atribuído!",
                        mensagem=f"Agente {agente.nome} assumiu chamado urgente"
                    )
                return True
        return False

    def _notificar_mudanca(self):
        """
        Emite evento WebSocket informando o estado atualizado do sistema.
        Inclui fila, agentes, ativos e em atendimento.
        """
        socketio.emit('atualizar_fila', {
            'fila': [self._serializar_chamado(c) for _, _, _, c in self.fila],
            'agentes': [self._serializar_agente(a) for a in self.agentes.values()],
            'chamados_ativos': [self._serializar_chamado(c) for c in self.chamados_ativos.values()],
            'chamados_em_atendimento': [self._serializar_chamado(c) for c in self.chamados_em_atendimento.values()]
        })

    def _serializar_chamado(self, chamado: ChamadoSuporte) -> dict:
        """
        Converte um ChamadoSuporte em dicionário para JSON.
        Formata prioridades, tempos e timestamps.
        """
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
        """
        Converte um AgenteSuporte em dicionário para JSON.
        Inclui especialidades e chamado atual.
        """
        return {
            "id": agente.id,
            "nome": agente.nome,
            "chamado_atual": agente.chamado_atual,
            "especialidades": [e.value for e in agente.especialidades]
        }

    @staticmethod
    def _enviar_notificacao(titulo: str, mensagem: str):
        """
        Dispara notificação desktop via plyer.
        """
        try:
            notification.notify(
                title=titulo,
                message=mensagem,
                app_name="Sistema de Chamados",
                timeout=10
            )
        except Exception as e:
            print(f"Erro ao enviar notificação: {e}")

# ----- Configuração inicial: criação do sistema e registro de agentes -----
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

# ----- Rotas HTTP para dashboard e API REST -----
@app.route('/')
def dashboard():
    """
    Rota principal que renderiza o dashboard HTML.
    """
    return render_template('dashboard.html')

@app.route('/api/chamados', methods=['GET', 'POST'])
def api_chamados():
    """
    GET: Retorna o estado atual (fila, agentes, atendimentos).
    POST: Recebe JSON e adiciona novo chamado.
    """
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
    """
    Ajusta prioridade de um chamado existente via API.
    """
    nova_prioridade = request.json.get('prioridade')
    if sistema.escalar_chamado(id_chamado, nova_prioridade):
        return jsonify({"status": "sucesso"})
    return jsonify({"erro": "Chamado não encontrado"}), 404

@app.route('/api/chamados/<id_chamado>/atribuir', methods=['PUT'])
def api_atribuir_chamado(id_chamado):
    """
    Atribui um agente ao chamado via API.
    """
    id_agente = request.json.get('id_agente')
    if sistema.atribuir_agente(id_chamado, id_agente):
        return jsonify({"status": "sucesso"})
    return jsonify({"erro": "Chamado ou agente não encontrado"}), 404

@app.route('/api/chamados/proximo', methods=['POST'])
def api_processar_chamado():
    """
    Remove e processa o próximo chamado da fila via API.
    """
    chamado = sistema.processar_proximo_chamado()
    if chamado:
        return jsonify(sistema._serializar_chamado(chamado))
    return jsonify({"erro": "Fila vazia"}), 404

@app.route('/api/chamados/<id_chamado>/finalizar', methods=['POST'])
def api_finalizar_chamado(id_chamado):
    """
    Finaliza um chamado em atendimento via API.
    """
    if sistema.finalizar_chamado(id_chamado):
        return jsonify({"status": "sucesso"})
    return jsonify({"erro": "Chamado não encontrado ou não está em atendimento"}), 404

# ----- Eventos WebSocket para atualização em tempo real -----
@socketio.on('connect')
def handle_connect():
    """
    Evento disparado quando um cliente WebSocket se conecta.
    Envia o estado inicial do sistema.
    """
    emit('atualizar_fila', {
        'fila': [sistema._serializar_chamado(c) for _, _, _, c in sistema.fila],
        'agentes': [sistema._serializar_agente(a) for a in sistema.agentes.values()],
        'chamados_em_atendimento': [sistema._serializar_chamado(c) for c in sistema.chamados_em_atendimento.values()]
    })

@socketio.on('novo_chamado')
def handle_novo_chamado(data):
    """
    Manipula evento de WebSocket para novo chamado.
    """
    sistema.adicionar_chamado(data)

@socketio.on('escalar_chamado')
def handle_escalar_chamado(data):
    """
    Manipula evento de WebSocket para escalonamento de chamado.
    """
    sistema.escalar_chamado(data['id_chamado'], data['prioridade'])

@socketio.on('finalizar_chamado')
