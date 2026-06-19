import json


data_questions = {
    "context_questions": {
        "question 1": "question",
        "question 2": "question",
        "question 3": "question",
        "question 4": "question",
        "question 5": "question"
    },
    "refinement_questions": {
        "question 1": "question",
        "question 2": "question",
        "question 3": "question",
        "question 4": "question",
        "question 5": "question"
    }
}

prompt_refine_questions = f"""
Você é um especialista em levantamento de requisitos e criação de briefings para projetos.

Analise as respostas fornecidas pelo usuário e gere exatamente 10 perguntas adicionais.

Regras:

1. As primeiras 5 perguntas devem ser personalizadas e baseadas diretamente nas respostas do usuário.
2. As últimas 5 perguntas devem ser perguntas de refinamento geral para obter mais contexto sobre o projeto.
3. As perguntas devem ser abertas e incentivar respostas detalhadas.
4. Evite repetir informações já fornecidas pelo usuário.
5. Foque em descobrir requisitos, objetivos, fluxos de trabalho, restrições, integrações e expectativas.
6. Retorne apenas um JSON válido.
7. Não inclua explicações, comentários ou texto adicional.

Formato de resposta:
{json.dumps(data_questions, ensure_ascii=False)}

IMPORTANTE:
- Não altere nenhuma chave.
- Não renomeie nenhuma chave.
- Não transforme objetos em listas.
- Não adicione campos extras.
- Preencha apenas os valores.

Respostas do usuário:
"""