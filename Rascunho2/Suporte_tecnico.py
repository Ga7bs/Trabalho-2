import heapq
from datetime import datetime
from dataclasses import dataclass, field
from typing import Tuple, Dict, Optional, List
from flask import Flask, request, jsonify
from plyer import notification
import logging
import threading
import time

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Constantes de priorização
PRIORIDADE_CHAMADO: Dict[str, int] = {
    'Server down': 1,
    'Impacta produção': 2,
    'Sem impacto': 3,
    'Dúvida': 4
}

PRIORIDADE_CLIENTE: Dict[str, int] = {
    'Prioritário': 1,
    'Sem prioridade': 2,
    'Demonstração': 3
}

@dataclass
class ChamadoSuporte:
    """Estrutura de dados para representar um chamado de suporte técnico"""
    id_chamado: int
    cliente_nome: str
    tipo_cliente: str
    tipo_chamado: str
    descricao: str
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Valida os tipos de chamado e cliente"""
        if self.tipo_cliente not in PRIORIDADE_CLIENTE:
            raise ValueError(f"Tipo de cliente inválido: {self.tipo_cliente}")
        if self.tipo_chamado not in PRIORIDADE_CHAMADO:
            raise ValueError(f"Tipo de chamado inválido: {self.tipo_chamado}")

def calcular_prioridade_combinada(tipo_chamado: str, tipo_cliente: str) -> Tuple[int, int]:
    """
    Calcula a prioridade combinada baseada no tipo de chamado e cliente
    
    Retorna:
        Tupla (prioridade_chamado, prioridade_cliente)
    """
    return (PRIORIDADE_CHAMADO[tipo_chamado], PRIORIDADE_CLIENTE[tipo_cliente])

def enviar_notificacao_desktop(titulo: str, mensagem: str) -> bool:
    """
    Envia notificação para a área de trabalho
    
    Retorna:
        True se bem sucedido, False caso contrário
    """
    try:
        notification.notify(
            title=titulo,
            message=mensagem,
            timeout=10,
            app_name="Suporte Técnico"
        )
        logger.info(f"Notificação enviada: {titulo}")
        return True
    except Exception as e:
        logger.error(f"Falha ao enviar notificação: {e}")
        return False

class FilaPrioridades:
    """
    Implementação da fila de prioridades usando heapq
    
    Complexidades:
    - Inserção: O(log n)
    - Remoção: O(log n)
    - Acesso ao próximo: O(1)
    """
    def __init__(self):
        self._heap = []
        self._index = 0
        self._lock = threading.Lock()
    
    def __len__(self) -> int:
        """Retorna o número de chamados na fila"""
        return len(self._heap)
    
    def adicionar_chamado(self, dados_chamado: dict) -> Optional[ChamadoSuporte]:
        """
        Adiciona um chamado à fila a partir de um dicionário
        
        Args:
            dados_chamado: Dicionário com os dados do chamado
            
        Returns:
            ChamadoSuporte ou None em caso de erro
        """
        try:
            chamado = ChamadoSuporte(**dados_chamado)
            prioridade = calcular_prioridade_combinada(chamado.tipo_chamado, chamado.tipo_cliente)
            
            with self._lock:
                heapq.heappush(
                    self._heap, 
                    (prioridade, chamado.timestamp.timestamp(), self._index, chamado)
                )
                self._index += 1
            
            logger.info(f"Chamado {chamado.id_chamado} adicionado com prioridade {prioridade}")
            return chamado
        except Exception as e:
            logger.error(f"Erro ao adicionar chamado: {e}")
            return None
    
    def processar_proximo_chamado(self) -> Optional[ChamadoSuporte]:
        """
        Processa o próximo chamado na ordem de prioridade
        
        Returns:
            ChamadoSuporte ou None se fila vazia
        """
        with self._lock:
            if not self._heap:
                return None
            
            prioridade, timestamp, _, chamado = heapq.heappop(self._heap)
        
        # Log do processamento
        logger.info(f"Processando chamado {chamado.id_chamado} - Prioridade: {prioridade}")
        print(f"\n=== Chamado Processado ===")
        print(f"ID: {chamado.id_chamado}")
        print(f"Cliente: {chamado.cliente_nome} ({chamado.tipo_cliente})")
        print(f"Tipo: {chamado.tipo_chamado}")
        print(f"Descrição: {chamado.descricao[:100]}...")
        print(f"Timestamp: {chamado.timestamp}\n")
        
        # Notificação para chamados críticos
        if prioridade[0] <= 2:  # Server down ou Impacta produção
            titulo = "Chamado Urgente na Fila!"
            mensagem = (
                f"Cliente: {chamado.cliente_nome} ({chamado.tipo_cliente})\n"
                f"Tipo: {chamado.tipo_chamado}\n"
                f"Descrição: {chamado.descricao[:50]}..."
            )
            enviar_notificacao_desktop(titulo, mensagem)
        
        return chamado
    
    def visualizar_fila(self) -> List[ChamadoSuporte]:
        """Retorna lista ordenada de chamados"""
        with self._lock:
            return [item[3] for item in sorted(self._heap)]

# Instância global da fila
fila_chamados = FilaPrioridades()

# Rotas da API
@app.route('/chamado', methods=['POST'])
def api_adicionar_chamado():
    """Endpoint para adicionar novo chamado"""
    data = request.json
    
    if not data:
        return jsonify({"status": "error", "message": "Dados não fornecidos"}), 400
    
    chamado = fila_chamados.adicionar_chamado(data)
    
    if chamado:
        return jsonify({
            "status": "success",
            "chamado": {
                "id": chamado.id_chamado,
                "cliente": chamado.cliente_nome,
                "tipo_cliente": chamado.tipo_cliente,
                "tipo_chamado": chamado.tipo_chamado,
                "timestamp": chamado.timestamp.isoformat()
            }
        }), 201
    
    return jsonify({
        "status": "error", 
        "message": "Falha ao adicionar chamado"
    }), 400

@app.route('/proximo_chamado', methods=['GET'])
def api_processar_chamado():
    """Endpoint para processar próximo chamado"""
    chamado = fila_chamados.processar_proximo_chamado()
    
    if chamado:
        return jsonify({
            "status": "success",
            "chamado": {
                "id": chamado.id_chamado,
                "cliente": chamado.cliente_nome,
                "tipo_cliente": chamado.tipo_cliente,
                "tipo_chamado": chamado.tipo_chamado,
                "descricao": chamado.descricao,
                "timestamp": chamado.timestamp.isoformat(),
                "prioridade": calcular_prioridade_combinada(
                    chamado.tipo_chamado, chamado.tipo_cliente
                )
            }
        }), 200
    
    return jsonify({
        "status": "error",
        "message": "Nenhum chamado na fila"
    }), 404

@app.route('/fila', methods=['GET'])
def api_visualizar_fila():
    """Endpoint para visualizar a fila"""
    chamados = fila_chamados.visualizar_fila()
    
    return jsonify({
        "status": "success",
        "count": len(chamados),
        "fila": [{
            "id": c.id_chamado,
            "cliente": c.cliente_nome,
            "tipo_cliente": c.tipo_cliente,
            "tipo_chamado": c.tipo_chamado,
            "timestamp": c.timestamp.isoformat(),
            "descricao": c.descricao,
            "prioridade": calcular_prioridade_combinada(
                c.tipo_chamado, c.tipo_cliente
            )
        } for c in chamados]
    }), 200

def processamento_automatico(intervalo=10):
    """Processa chamados automaticamente em intervalos regulares"""
    while True:
        fila_chamados.processar_proximo_chamado()
        time.sleep(intervalo)

if __name__ == '__main__':
    # Exemplos para teste
    exemplos = [
        {
            "id_chamado": 1,
            "cliente_nome": "Empresa A",
            "tipo_cliente": "Demonstração",
            "tipo_chamado": "Dúvida",
            "descricao": "Como gerar relatório?"
        },
        {
            "id_chamado": 2,
            "cliente_nome": "Empresa B",
            "tipo_cliente": "Prioritário",
            "tipo_chamado": "Server down",
            "descricao": "Servidor principal offline"
        },
        {
            "id_chamado": 3,
            "cliente_nome": "Empresa C",
            "tipo_cliente": "Sem prioridade",
            "tipo_chamado": "Impacta produção",
            "descricao": "Módulo de vendas não funciona"
        }
    ]
    
    for ex in exemplos:
        fila_chamados.adicionar_chamado(ex)
    
    # Iniciar processamento automático em segundo plano
    processador = threading.Thread(target=processamento_automatico, daemon=True)
    processador.start()
    
    # Iniciar API
    app.run(host='0.0.0.0', port=5000, debug=True)