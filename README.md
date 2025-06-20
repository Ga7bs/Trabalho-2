# Sistema de Chamadas

Uma aplicação web simples para gerenciamento de chamadas, utilizando Flask e Socket.IO.

## 🚀 Como executar o projeto

### 📦 Dependências

Instale as dependências necessárias com o `pip`:

```bash
pip install flask flask-sse flask-socketio plyer redis
```

Caso o Redis não seja necessário para sua execução local, utilize:

```bash
pip install flask flask-socketio flask-sse plyer
```

### ▶️ Executando a aplicação

Execute o script principal:

```bash
python Sistema_Chamadas.py
```
### 🌐 Acessando o Dashboard

Abra seu navegador e acesse:

[http://localhost:5000](http://localhost:5000)

## 🛠️ Tecnologias Utilizadas

- [Flask](https://flask.palletsprojects.com/)
- [Flask-SocketIO](https://flask-socketio.readthedocs.io/)
- [Flask-SSE](https://flask-sse.readthedocs.io/)
- [Redis](https://redis.io/)
- [Plyer](https://github.com/kivy/plyer)

---

# Análise de Complexidade e Escalabilidade:
## ⚙️ Operações Principais

- `adicionar_chamado()`: O(log n) — devido ao uso de `heapq.heappush`
- `processar_proximo_chamado()`: O(log n) — devido ao uso de `heapq.heappop`


## 🔄 Comparação com Alternativas

### Lista não ordenada
- Inserção: O(1)
- Remoção: O(n) — é necessário buscar o item mais prioritário manualmente

### Lista ordenada
- Inserção: O(n) — para manter a ordenação
- Remoção: O(1) — sempre remove o primeiro item (de maior prioridade)


Notificações são disparadas automaticamente para:
    'Server down' (prioridade 1)
    'Impacta produção' (prioridade 2)