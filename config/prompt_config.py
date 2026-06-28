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
    "business_model": {
        "industry": "",
        "products_services": [],
        "business_model": "",
        "market_stage": ""
    },
    "target_audience": {
        "primary_audience": "",
        "secondary_audience": "",
        "buyer_personas": [],
        "pain_points": [],
        "goals": [],
        "motivations": [],
        "objections": []
    },
    "market_analysis": {
        "competitors": [],
        "competitive_advantages": [],
        "market_gaps": [],
        "market_trends": [],
        "opportunities": [],
        "threats": []
    },
    "brand_positioning": {
        "market_position": "",
        "unique_selling_proposition": "",
        "desired_perception": ""
    },
    "brand_personality": {
        "brand_archetype": "",
        "personality_traits": [],
        "brand_emotions": [],
        "tone_of_voice": "",
        "communication_style": "",
        "brand_keywords": []
    },
    "verbal_identity": {
        "tagline": "",
        "key_messages": [],
        "words_to_use": [],
        "words_to_avoid": []
    },
    "visual_identity": {
        "style": "",
        "logo_direction": "",
        "logo_symbolism": "",

        "logo_concepts": [
            {
                "concept": "",
                "reason": ""
            }
        ],
        "recommended_logo_types": [],
        "typography_direction": "",

        "composition_style": "",
        "negative_space_usage": "",
        "border_style": "",

        "iconography": "",
        "photography_style": "",
        "illustration_style": "",

        "recommended_shapes": [],
        "recommended_symbols": [],
        "recommended_textures": [],
        "recommended_patterns": [],

        "styles_to_avoid": [],

        "visual_inspirations": {
            "brands": [
                {
                    "name": "",
                    "reason": ""
                }
            ],
            "design_movements": [],
            "references": []
        }
    },
    "color_strategy": {
        "emotions": [],
        "brand_association": "",
        "overall_reason": ""
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
    "application_scenarios": [
        {
            "application": "",
            "priority": "",
            "reason": ""
        }
    ],
    "swot_analysis": {
        "strengths": [],
        "weaknesses": [],
        "opportunities": [],
        "threats": [],
        "strategic_summary": ""
    },
    "briefing_analysis": {
        "confidence_score": "",
        "contradictory_points": [],
        "missing_information": [],
        "risk_factors": []
    },
    "strategic_recommendations": {
        "short_term": [],
        "medium_term": [],
        "long_term": []
    },
    "designer_notes": {
        "logo": [],
        "colors": [],
        "typography": [],
        "applications": []
    },
    "next_steps": [
        {
            "step": "",
            "priority": "",
            "reason": ""
        }
    ]
}

prompt_generate_briefing = f"""
Você é um especialista sênior em branding, posicionamento de marca, estratégia de negócios, marketing, comportamento do consumidor e identidade visual.

Analise cuidadosamente todas as respostas fornecidas pelo cliente e gere um briefing estratégico completo para orientar designers, estrategistas e profissionais de branding na construção da identidade da marca.

Regras:

1. Utilize todas as respostas fornecidas pelo cliente.
2. Extraia informações estratégicas para preencher todos os campos do JSON.
3. Faça inferências apenas quando forem consistentes com o contexto.
4. Nunca contradiga informações fornecidas pelo cliente.
5. Caso uma informação não exista e não possa ser inferida, utilize:
    - "" para textos;
    - [] para listas.
6. Mantenha consistência entre todos os campos do JSON, evitando informações conflitantes ou repetidas.
7. Cada seção deve complementar as demais, sem duplicar conteúdo.
8. As recomendações devem ser objetivas, práticas e acionáveis.
9. Retorne somente um JSON válido seguindo exatamente a estrutura fornecida.
10. Não altere, remova, renomeie ou adicione chaves. Não altere os tipos dos campos.

Formato de resposta:
{json.dumps(data_response, ensure_ascii=False)}

IMPORTANTE:

- Preencha todos os campos.
- Não escreva explicações, comentários ou markdown.
- O resultado deve representar um briefing profissional pronto para uso por designers, estrategistas e profissionais de branding.

Respostas do cliente:
"""