function initDashboard() {
    // Define um ouvinte (listener) para o evento 'fila_atualizada'.
        // Toda vez que o servidor enviar esse evento, a função será executada.
    
    const socket = io();
    // Cria uma conexão WebSocket usando a biblioteca Socket.io.
    // Permite comunicação em tempo real entre o servidor e o cliente (navegador).
    
    socket.on('fila_atualizada', function(data) {
        // Atualizar fila de chamados
        // Define um ouvinte (listener) para o evento 'fila_atualizada'.
        // Toda vez que o servidor enviar esse evento, a função será executada.

        // === Atualização da fila de chamados ===
        const filaDiv = document.getElementById('fila');
         // Seleciona o elemento HTML com id 'fila', onde serão exibidos os chamados.

        filaDiv.innerHTML = '';
         // Limpa o conteúdo atual da fila antes de inserir os novos dados.

        data.fila.forEach(chamado => {
            const div = document.createElement('div');
            div.className = `chamado prioridade-${chamado.prioridade[0]}`;
            div.innerHTML = `
                <h3>${chamado.cliente_nome} - ${chamado.tipo_chamado}</h3>
                <p>Prioridade: ${chamado.prioridade.join(',')}</p>
                <p>Tempo estimado: ${chamado.tempo_estimado}</p>
                <p>Agente: ${chamado.agente_atribuido || 'Não atribuído'}</p>
            `;
            filaDiv.appendChild(div);
        });
        
        // Atualizar agentes
        const agentesDiv = document.getElementById('agentes');
        agentesDiv.innerHTML = '';
        
        data.agentes.forEach(agente => {
            const div = document.createElement('div');
            div.className = 'agente';
            div.innerHTML = `
                <h3>${agente.nome}</h3>
                <p>Chamado atual: ${agente.chamado_atual || 'Nenhum'}</p>
            `;
            agentesDiv.appendChild(div);
        });
    });
}
