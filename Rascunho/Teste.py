from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Estrutura de exemplo para armazenamento em memória
dados = []

# Modelo de item
class Item(BaseModel):
    nome: str

@app.get("/")  # Rota para o método GET na raiz do aplicativo
async def ler_root():
    return {"mensagem": "Bem-vindo ao FastAPI!"}

@app.post("/itens/")  # Rota para criar um item
async def criar_item(item: Item):
    if not item.nome:
        raise HTTPException(status_code=400, detail="Item não pode ser vazio.")
    dados.append(item.nome)
    return {"mensagem": "Item adicionado com sucesso!", "item": item.nome}

@app.get("/itens/")  # Rota para listar itens
async def listar_itens():
    return {"itens": dados}