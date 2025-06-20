# Sistema de gerenciamento de chamados de suporte técnico com priorização automática, notificações e interface web.

import heapq # Permite manipular listas de modo que elas possam ser usadas como filas de prioridade, onde o menor 
# elemento sempre fica na frente.

import time # Medir o tempo de execução de blocos de código. Implementar atrasos ou intervalos. Obter timestamps para 
# logs ou armazenamento.

from datetime import datetime, timedelta # Gerenciamento de tempo e datas
from dataclasses import dataclass, field # Definir estruturas de dados simples de forma clara e concisa.
# Melhorar a legibilidade e manutenção do código.

from typing import Optional, List, Dict # Documentar tipos de variáveis e funções. Melhorar a clareza do código e 
# suporte a ferramentas de análise.

from enum import Enum # Representar estados ou opções fixas de forma clara. Garantir que variáveis assumam apenas 
# valores definidos.

from flask import Flask, request, jsonify, render_template # Desenvolvimento web e comunicação em tempo real.
# Criar rotas que respondem a requisições HTTP. Desenvolver APIs RESTful. Servir páginas HTML dinâmicas.

from flask_sse import sse # Notificações em tempo real. Atualizações ao vivo em dashboards ou aplicações web.

from flask_socketio import SocketIO, emit # Permite a comunicação bidirecional em tempo real entre cliente e servidor.

from plyer import notification # Enviar notificações de tarefas concluídas, alertas ou lembretes. Integrar notificações
# em aplicações desktop ou móveis.
###################################################################################################
# Criar a aplicação web e permitir comunicação em tempo real.
###################################################################################################
app = Flask(__name__) # Diz ao Flask onde procurar por templates, arquivos estáticos (CSS/JS).
app.config["SECRET_KEY"] = "secret!" #Essa chave é usada para criptografar dados.
# Permitir que múltiplos workers/processos do Flask compartilhem dados.
app.config["REDIS_URL"] = "redis://localhost" # Comunicação em tempo real. 
# Permite que o servidor envie atualizações para o cliente sem necessidade de requisições (ex: notificações).
app.register_blueprint(sse, url_prefix='/stream') 
# Habilita comunicação bidirecional em tempo real entre cliente e servidor (ex: atualizações da fila de chamados).
socketio = SocketIO(app)

###################################################################################################
# Define a estrutura básica de tipos, prioridades e tempos de resolução para o sistema de chamados.
###################################################################################################
# Enums para tipos estruturados. Define os tipos de chamados que o sistema suporta, com descrições amigáveis.
class TipoChamado(Enum):
    SERVER_DOWN = "Server down" # Servidor offline. Chamado crítico (prioridade máxima).
    IMPACTA_PRODUCAO = "Impacta produção" # Exemplo: Aplicação lenta.
    SEM_IMPACTO = "Sem impacto" # Exemplo: Problema cosmético.
    DUVIDA = "Dúvida" # Chamado de baixa prioridade. Como usar um recurso.

# Classifica os clientes por importância.
class TipoCliente(Enum):
    PRIORITARIO = "Prioritário" # Exemplo: Cliente que paga plano premium.
    SEM_PRIORIDADE = "Sem prioridade" # Cliente comumm.
    DEMONSTRACAO = "Demonstração" # Exemplo: Teste gratuito.

# Controla o ciclo de vida de um chamado.
class StatusChamado(Enum):
    PENDENTE = "Pendente" # Aguardando atendimento.
    EM_ATENDIMENTO = "Em atendimento" # Em progresso.
    RESOLVIDO = "Resolvido" # Finalizado.

# Define a ordem de prioridade. Mapeia cada tipo de chamado para uma prioridade numérica (quanto menor, mais urgente). 
PRIORIDADE_CHAMADO = {
    TipoChamado.SERVER_DOWN: 1, # Máxima urgência.
    TipoChamado.IMPACTA_PRODUCAO: 2, # Alta urgência.
    TipoChamado.SEM_IMPACTO: 3, # Média urgência.
    TipoChamado.DUVIDA: 4 # Baixa urgência.
}

# Define a prioridade baseada no cliente.
PRIORIDADE_CLIENTE = {
    TipoCliente.PRIORITARIO: 1, # Cliente VIP.
    TipoCliente.SEM_PRIORIDADE: 2, # Cliente normal.
    TipoCliente.DEMONSTRACAO: 3 # Cliente de teste.
}

# Estipula tempos máximos de resolução (em minutos) para cada tipo de chamado.
# Ex: notificar se um SERVER_DOWN está demorando mais que 2 horas.
TEMPO_RESOLUCAO = {
    TipoChamado.SERVER_DOWN: 120, # 2 horas.
    TipoChamado.IMPACTA_PRODUCAO: 60, # 1 hora.
    TipoChamado.SEM_IMPACTO: 30, # 30 minutos.
    TipoChamado.DUVIDA: 15 # 15 minutos.
}
"""Um chamado é criado Seu tipo (TipoChamado) e cliente (TipoCliente) definem sua prioridade combinada (usando 
PRIORIDADE_CHAMADO e PRIORIDADE_CLIENTE) usada para ordenar a fila. O sistema usa TEMPO_RESOLUCAO para estimar quando 
o chamado deve ser  resolvido. O StatusChamado é atualizado conforme o chamado progride (PENDENTE → EM_ATENDIMENTO → 
RESOLVIDO)."""

###################################################################################################
# Modela um agente de suporte técnico.
###################################################################################################
@dataclass
class AgenteSuporte:
    id: str # Identificador único (ex: "ag1").
    nome: str # Nome do agente (ex: "Madonna").
    especialidades: List[TipoChamado] # Lista de tipos de chamados que o agente pode atender (ex: 
    #[TipoChamado.SERVER_DOWN, TipoChamado.IMPACTA_PRODUCAO]).
    chamado_atual: Optional[str] = None # ID do chamado que o agente está atendendo no momento (ou None se livre).

###################################################################################################
# Permite ordenar objetos ChamadoSuporte (usado na fila prioritária).
###################################################################################################
@dataclass(order=True)
class ChamadoSuporte:
    id_chamado: str # ID único (ex: "INC-1").
    cliente_nome: str # Nome do cliente que abriu o chamado.
    tipo_cliente: TipoCliente # Prioridade do cliente (PRIORITARIO, SEM_PRIORIDADE, etc.).
    tipo_chamado: TipoChamado # Natureza do problema (SERVER_DOWN, DUVIDA, etc.).
    descricao: str # Detalhes do chamado.
    status: StatusChamado = StatusChamado.PENDENTE # Estado atual (PENDENTE, EM_ATENDIMENTO, RESOLVIDO).
    timestamp: datetime = field(default_factory=datetime.now) # Data/hora de criação (preenchida automaticamente).
    prioridade_manual: Optional[int] = None # Prioridade sobrescrita (se não None).
    agente_atribuido: Optional[str] = None # ID do agente responsável (ou None).
    tempo_estimado: timedelta = field(init=False) # Tempo estimado para resolução (calculado após inicialização).

# Calcula o tempo_estimado com base no tipo_chamado usando o dicionário TEMPO_RESOLUCAO.
    def __post_init__(self):
        self.tempo_estimado = timedelta(minutes=TEMPO_RESOLUCAO[self.tipo_chamado])

    def prioridade_combinada(self) -> tuple:
        """Calcula a prioridade considerando a manual se existir"""
        # Usa prioridade_manual se definida; caso contrário, pega o valor padrão de PRIORIDADE_CHAMADO.
        prioridade_chamado = self.prioridade_manual or PRIORIDADE_CHAMADO[self.tipo_chamado]
        # Obtém do dicionário PRIORIDADE_CLIENTE.
        prioridade_cliente = PRIORIDADE_CLIENTE[self.tipo_cliente]
        return (prioridade_chamado, prioridade_cliente) # Retorna uma tupla (prioridade_chamado, prioridade_cliente).
    """Essa tupla é usada para ordenar os chamados na fila. Compara o primeiro elemento (prioridade_chamado). Em caso 
    de empate, compara o segundo (prioridade_cliente). definindo como chamados e agentes são modelados e como as 
    prioridades são calculadas."""

###################################################################################################
# Inicializa todas as estruturas de dados necessárias para o sistema.
###################################################################################################
class SistemaChamados:
    def __init__(self):
        self.fila = [] # Fila prioritária de chamados (heap).
        self.contador = 0  # Contador para desempate na fila.
        self.agentes: Dict[str, AgenteSuporte] = {} # Dicionário de agentes (id → objeto).
        self.chamados_ativos: Dict[str, ChamadoSuporte] = {} # Todos os chamados não resolvidos.
        self.ultimo_id = 0 # Contador para gerar IDs únicos.
        self.chamados_em_atendimento: Dict[str, ChamadoSuporte] = {}  #Chamados sendo atendidos.

# Cria IDs sequenciais para chamados (ex: INC-1, INC-2).
    def _gerar_id(self) -> str:
        self.ultimo_id += 1
        return f"INC-{self.ultimo_id}"

# Armazena um agente no dicionário self.agentes, usando seu ID como chave.
    def adicionar_agente(self, agente: AgenteSuporte):
        self.agentes[agente.id] = agente

# Passos da função def adicionar_chamado() 1ª Gera um ID se não fornecido.  
    def adicionar_chamado(self, dados_chamado: dict) -> Optional[ChamadoSuporte]:
        try:
            if 'id_chamado' not in dados_chamado or not dados_chamado['id_chamado']:
                dados_chamado['id_chamado'] = self._gerar_id()

            # 2ª Cria o objeto ChamadoSuporte.
            chamado = ChamadoSuporte( 
                id_chamado=dados_chamado['id_chamado'],
                cliente_nome=dados_chamado['cliente_nome'],
                tipo_cliente=TipoCliente(dados_chamado['tipo_cliente']),
                tipo_chamado=TipoChamado(dados_chamado['tipo_chamado']),
                descricao=dados_chamado['descricao'],
                prioridade_manual=dados_chamado.get('prioridade_manual')
            )
            # 3ª Adiciona à fila prioritária usando heapq.heappush. 4ª Armazena em chamados_ativos.
            heapq.heappush(
                self.fila,
                (chamado.prioridade_combinada(), chamado.timestamp, self.contador, chamado)
            )
            self.contador += 1
            self.chamados_ativos[chamado.id_chamado] = chamado
            
            # 5ª Envia notificações se for urgente. Notificação automática para alta prioridade.
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

   # Altera a prioridade manual de um chamado e reorganiza a fila.
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

   # Verifica se chamado e agente existem.
    def atribuir_agente(self, id_chamado: str, id_agente: str) -> bool:
        if id_chamado not in self.chamados_ativos or id_agente not in self.agentes:
            return False
        
        chamado = self.chamados_ativos[id_chamado]
        agente = self.agentes[id_agente]
        
        # Liberar agente atual se estiver ocupado.
        if agente.chamado_atual:
            self.chamados_ativos[agente.chamado_atual].agente_atribuido = None
            self.chamados_ativos[agente.chamado_atual].status = StatusChamado.PENDENTE
        
        chamado.agente_atribuido = id_agente
        chamado.status = StatusChamado.EM_ATENDIMENTO
        agente.chamado_atual = id_chamado
        
        # Mover para a lista de em atendimento. Atualiza os status e referências.
        self.chamados_em_atendimento[id_chamado] = chamado
        
        self._notificar_mudanca()
        return True

# Remove o chamado mais prioritário da fila.
    def processar_proximo_chamado(self) -> Optional[ChamadoSuporte]:
        if not self.fila:
            return None

        _, _, _, chamado = heapq.heappop(self.fila)
        chamado.status = StatusChamado.EM_ATENDIMENTO
        
        # Atribuir automaticamente a um agente disponível. Busca um agente compatível e disponível.
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

# Altera status para RESOLVIDO. Libera o agente e tenta atribuir outro chamado.
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
        # Emite eventos via SocketIO para atualizar a interface em tempo real.
        self._notificar_mudanca()
        return True

# Tenta atribuir automaticamente o próximo chamado compatível a um agente liberado.
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

# Convertem objetos em dicionários para envio via API/WebSocket.
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

# Emite eventos via SocketIO para atualizar a interface em tempo real.
    def _serializar_agente(self, agente: AgenteSuporte) -> dict:
        return {
            "id": agente.id,
            "nome": agente.nome,
            "chamado_atual": agente.chamado_atual,
            "especialidades": [e.value for e in agente.especialidades]
        }

# Envia alertas desktop usando plyer.notification.
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

# Configuração inicial do sistema. Cria dois agentes de exemplo com especialidades distintas.
sistema = SistemaChamados()
sistema.adicionar_agente(AgenteSuporte(
    id="ag1",
    nome="Madonna",
    especialidades=[TipoChamado.SERVER_DOWN, TipoChamado.IMPACTA_PRODUCAO]
))
sistema.adicionar_agente(AgenteSuporte(
    id="ag2",
    nome="Schwarzenegger",
    especialidades=[TipoChamado.SEM_IMPACTO, TipoChamado.DUVIDA]
))

#####################################################################################################
# Rotas que permite ao frontend interagir com o sistema de chamados de forma organizada e previsível.
#####################################################################################################
# Renderiza a página HTML principal (dashboard.html) que será a interface do usuário.
# Rotas da API
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# POST: Cria um novo chamado com os dados enviados no corpo da requisição (JSON).
# GET: Retorna o estado atual do sistema em JSON como fila: fila -> Chamados pendentes (ordenados por prioridade),
# agentes -> Lista de agentes e seus status e chamados_em_atendimento -> Chamados sendo resolvidos.
# A interface web consome essa rota para atualizar o dashboard.
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

# PUT: Altera a prioridade manual de um chamado existente. Efeito colateral: Reorganiza a fila prioritária 
# (heapq.heapify).
@app.route('/api/chamados/<id_chamado>/escalar', methods=['PUT'])
def api_escalar_chamado(id_chamado):
    nova_prioridade = request.json.get('prioridade')
    if sistema.escalar_chamado(id_chamado, nova_prioridade):
        return jsonify({"status": "sucesso"})
    return jsonify({"erro": "Chamado não encontrado"}), 404

# PUT: Atribui um chamado a um agente específico. Se o agente já estiver ocupado, o chamado atual é liberado.
@app.route('/api/chamados/<id_chamado>/atribuir', methods=['PUT'])
def api_atribuir_chamado(id_chamado):
    id_agente = request.json.get('id_agente')
    if sistema.atribuir_agente(id_chamado, id_agente):
        return jsonify({"status": "sucesso"})
    return jsonify({"erro": "Chamado ou agente não encontrado"}), 404

# POST: Pega o próximo chamado da fila (prioridade mais alta) e tenta atribuir a um agente disponível.
# Usa heapq.heappop para pegar o chamado mais urgente.
@app.route('/api/chamados/proximo', methods=['POST'])
def api_processar_chamado():
    chamado = sistema.processar_proximo_chamado()
    if chamado:
        return jsonify(sistema._serializar_chamado(chamado))
    return jsonify({"erro": "Fila vazia"}), 404

# POST: Marca um chamado como resolvido e libera o agente para o próximo. Chama _atribuir_proximo_chamado para 
# realocar o agente.
@app.route('/api/chamados/<id_chamado>/finalizar', methods=['POST'])
def api_finalizar_chamado(id_chamado):
    if sistema.finalizar_chamado(id_chamado):
        return jsonify({"status": "sucesso"})
    return jsonify({"erro": "Chamado não encontrado ou não está em atendimento"}), 404


###########################################################################################################
# WebSocket: é responsável pela comunicação em tempo real entre o servidor e os clients (como navegadores).
###########################################################################################################

# O servidor envia imediatamente o estado atual do sistema: Fila de chamados (ordenada por prioridade), lista de 
# agentes (com status e especialidades) e chamados em atendimento. Os dados são serializados (convertidos para JSON) 
# usando os métodos _serializar_chamado e _serializar_agente.
@socketio.on('connect')
def handle_connect():
    emit('atualizar_fila', {
        'fila': [sistema._serializar_chamado(c) for _, _, _, c in sistema.fila],
        'agentes': [sistema._serializar_agente(a) for a in sistema.agentes.values()],
        'chamados_em_atendimento': [sistema._serializar_chamado(c) for c in sistema.chamados_em_atendimento.values()]
    })

# O cliente envia um evento novo_chamado com os dados do chamado (ex: tipo, cliente, descrição). O servidor chama 
# sistema.adicionar_chamado(data) para adicionar à fila prioritária e notificar todos os clients via 
# _notificar_mudanca() (que emite atualizar_fila).
@socketio.on('novo_chamado')
def handle_novo_chamado(data):
    sistema.adicionar_chamado(data)

# O cliente envia o ID do chamado e a nova prioridade (ex: { id_chamado: "INC-1", prioridade: 1 }). O servidor: 
# Atualiza a prioridade no sistema, reorganiza a fila com heapq.heapify, notifica todos os clients sobre a mudança.
# Efeito colateral: A interface de todos os clients é atualizada em tempo real.
@socketio.on('escalar_chamado')
def handle_escalar_chamado(data):
    sistema.escalar_chamado(data['id_chamado'], data['prioridade'])

# O cliente envia o ID do chamado a ser finalizado. O servidor: Muda o status para RESOLVIDO, libera o agente vinculado,
# atribui automaticamente o próximo chamado (se houver) e notifica todos os clients.
@socketio.on('finalizar_chamado')
def handle_finalizar_chamado(data):
    sistema.finalizar_chamado(data['id_chamado'])

# debug=True	Ativa modo de desenvolvimento (recarrega o servidor automaticamente).
# host='0.0.0.0'	Permite conexões de qualquer IP (útil para testes em rede local).
if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0')
