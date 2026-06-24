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

prompt_questions_personalized = f"""
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

data_response = {
    "executive_summary": "",
    "brand_foundation": {
        "business_description": "",
        "problem_solved": "",
        "mission": "",
        "vision": "",
        "values": [],
        "purpose": ""
    },
    "target_audience": {
        "primary_audience": "",
        "secondary_audience": "",
        "pain_points": [],
        "goals": [],
        "motivations": [],
        "objections": []
    },
    "brand_positioning": {
        "market_position": "",
        "unique_selling_proposition": "",
        "desired_perception": ""
    },
    "competitive_analysis": {
        "competitors": [],
        "competitive_advantages": []
    },
    "brand_personality": {
        "personality_traits": [],
        "brand_archetype": "",
        "tone_of_voice": "",
        "communication_style": ""
    },
    "color_palette": {
        "primary_color": {
            "name": "",
            "hex": "",
            "reason": ""
        },
        "secondary_color": {
            "name": "",
            "hex": "",
            "reason": ""
        },
        "accent_color": {
            "name": "",
            "hex": "",
            "reason": ""
        },
        "neutral_colors": [
            {
                "name": "",
                "hex": "",
                "reason": ""
            }
        ]
    },
    "brand_attributes": {
        "must_communicate": [],
        "must_avoid": []
    },
    "briefing_analysis": {
        "contradictory_points": [],
        "missing_information": [],
        "risk_factors": []
    },
    "application_scenarios": [],
    "strategic_recommendations": [],
    "designer_notes": []
}

prompt_generate_briefing = f"""
Você é um especialista sênior em branding, posicionamento de marca, estratégia de negócios e identidade visual.

Analise todas as respostas fornecidas pelo cliente e gere um briefing estratégico completo para orientar designers e profissionais de branding na criação da identidade visual da marca.

Regras:

1. Utilize todas as respostas fornecidas pelo cliente.
2. Extraia informações estratégicas relevantes para a construção da marca.
3. Identifique objetivos, diferenciais, público-alvo, posicionamento e personalidade da marca.
4. Identifique concorrentes mencionados ou inferidos a partir do contexto.
5. Identifique diferenciais competitivos da marca.
6. Identifique possíveis contradições, inconsistências ou conflitos nas respostas do cliente.
7. Sugira uma direção visual coerente com o contexto do negócio.
8. Sugira uma paleta de cores estratégica com justificativas para cada cor.
9. Sugira um arquétipo de marca compatível com as informações fornecidas.
10. Sugira direcionamentos para logotipo, tipografia e comunicação visual.
11. Não invente informações que contradigam as respostas do cliente.
12. Faça inferências estratégicas apenas quando forem razoáveis e consistentes com o contexto.
13. Retorne apenas JSON válido.
14. Não inclua explicações, comentários ou texto adicional.

Formato de resposta:
{json.dumps(data_response, ensure_ascii=False)}

IMPORTANTE:

- Não altere nenhuma chave.
- Não renomeie nenhuma chave.
- Não transforme objetos em listas.
- Não adicione campos extras.
- Preencha apenas os valores.
- Todos os campos devem ser preenchidos da forma mais completa possível.
- Caso não existam contradições identificáveis, retorne uma lista vazia.
- Caso não existam concorrentes informados, utilize concorrentes inferidos apenas quando houver contexto suficiente.

Respostas do cliente:
"""