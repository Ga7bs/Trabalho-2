// ###########################################################################################
// Responsável por gerenciar a atualização dinâmica da interface do usuário via WebSocket.
// Todas as mudanças no servidor são refletidas instantaneamente na interface do usuário.
// ###########################################################################################

// Inicializa o dashboard, criando uma conexão WebSocket com o servidor usando socket.io.
function initDashboard() {
    const socket = io();
    
    // Escuta o evento fila_atualizada emitido pelo servidor sempre que há mudanças nos chamados ou agentes.
    // Quando é acionado: Novo chamado criado, chamado finalizado, agente atribuído a um chamado e prioridade alterada.
    socket.on('fila_atualizada', function(data) {

        // Atualizar fila de chamados
        // Limpeza: filaDiv.innerHTML = '' remove todos os chamados atualmente exibidos.
        // Iteração: Para cada chamado no array data.fila, cria um novo elemento <div>.
        // Estilização: prioridade-${chamado.prioridade[0]}: Aplica uma classe CSS baseada na prioridade (ex: 
        // prioridade-1 para urgente).
        // Conteúdo: Preenche o HTML com os dados do chamado: Nome do cliente e tipo de chamado, prioridade (ex: 1,3 
        // onde 1 = prioridade do chamado, 3 = prioridade do cliente), tempo estimado para resolução, agente atribuído
        // (ou "Não atribuído").
        const filaDiv = document.getElementById('fila');
        filaDiv.innerHTML = '';
        
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
        // Limpeza: agentesDiv.innerHTML = '' remove a lista atual de agentes.
        // Iteração: Para cada agente no array data.agentes, cria um novo elemento <div>.
        // Conteúdo: Nome do agente e chamado atual (ou "Nenhum" se estiver livre).
        // Estilização: A classe agente provavelmente está definida no CSS para estilizar os cards (ex: bordas, cores).
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