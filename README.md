# misa-flask-api

<!-- markdownlint-disable MD033 -->

<div align="center">
  <img src=".github/label-logo.png" alt="Label Logo" width="130">
  <h1><b>Misa Flask API</b></h1>
  <p>AI-powered Flask API to generate brand identity briefings through adaptive questionnaires.</p>
  <p>
    <img src="https://img.shields.io/github/last-commit/id0ubl3g/misa-flask-api?style=flat&logo=git&logoColor=white&color=0080ff" alt="Last Commit">
    <img src="https://img.shields.io/github/languages/top/id0ubl3g/misa-flask-api?style=flat&color=0080ff" alt="Top Language">
    <img src="https://img.shields.io/github/languages/count/id0ubl3g/misa-flask-api?style=flat&color=0080ff" alt="Languages Count">
  </p>
</div>

<!-- markdownlint-enable MD033 -->

## Table of Contents

* [Overview](#overview)
* [Features](#features)
* [Project Structure](#project-structure)
* [Prerequisites](#prerequisites)
* [Install Docker](#install-docker)
* [Environment Configuration](#environment-configuration)
* [Running the Application](#running-the-application)
* [Production Deployment](#production-deployment)
* [API Documentation](#api-documentation)
  * [Endpoints](#endpoints)
  * [Core Endpoints](#core-endpoints)
    * [Create Client for Brand Briefing](#create-client-for-brand-briefing)
  * [Example Use Case](#example-use-case)
    * [Frontend Integration Create Client](#frontend-integration-create-client)
* [Acknowledgments](#acknowledgments)
* [License](#license)

## Overview

The Misa Flask API is a web application developed with Flask, designed to generate brand identity briefings through adaptive questionnaires. The API allows designers to create clients, collect information through initial and personalized questions, and use generative AI to produce structured brand briefing data.

## Features

* AI-powered brand identity briefing generation
* Adaptive questionnaires for clients
* Initial and personalized questionnaire flows
* Selectable AI provider: OpenAI or Google Gemini (Vertex AI)
* JWT-based authentication
* Client management
* MongoDB data persistence (self-hosted container)
* Redis caching and rate limiting (self-hosted container)
* Firebase authentication
* Google authentication
* Mercado Pago subscription integration
* RabbitMQ queue and worker for asynchronous AI briefing generation
* Docker and Docker Compose support
* Automatic HTTPS in production through Caddy

## Project Structure

```plaintext
└── misa-flask-api/
    ├── .github/
    │   └── label-logo.png
    ├── config/
    │   ├── model_initial_questions.py
    │   ├── model_questions_personalized.py
    │   ├── path_config.py
    │   ├── prompt_config.py
    │   └── providers/
    │       ├── initialize_firebase.py
    │       ├── initialize_mercadopago.py
    │       ├── initialize_mongodb.py
    │       └── initialize_redis.py
    ├── src/
    │   ├── api/
    │   │   └── app.py
    │   ├── modules/
    │   │   ├── open_ai.py
    │   │   └── vertex_ai.py
    │   ├── rabbitmq/
    │   │   ├── connection.py
    │   │   └── publisher.py
    │   ├── workers/
    │   │   └── briefing_worker.py
    │   └── utils/
    │       ├── return_responses.py
    │       └── system_utils.py
    ├── .dockerignore
    ├── .env.example
    ├── .gitignore
    ├── Caddyfile
    ├── docker-compose.yml
    ├── Dockerfile
    ├── LICENSE
    ├── Makefile
    ├── README.md
    ├── requirements.txt
    └── run.py
```

## Prerequisites

To run the Misa Flask API, use a Linux environment with Docker and Docker Compose. MongoDB, Redis and RabbitMQ run as containers alongside the API, so no external database is needed. Internet access is required for the external services:

* Firebase (Google sign-in)
* Mercado Pago (subscriptions)
* OpenAI API, or Google Cloud Vertex AI when `AI_PROVIDER=gemini`

### Install Docker

On Ubuntu or Debian, install Docker and the Compose plugin with the official script, then allow your user to run it without `sudo`:

```sh
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
docker --version && docker compose version
```

For other systems, follow the official guide: [https://docs.docker.com/engine/install/](https://docs.docker.com/engine/install/)

## Environment Configuration

Create the environment file from the provided example:

```sh
cp .env.example .env
```

Configure the required environment variables in `.env`:

| Variable | Description |
| --- | --- |
| `JWT_SECRET_KEY` | Secret used to sign the API access and refresh tokens. |
| `MONGO_ROOT_USER`, `MONGO_ROOT_PASS` | Credentials of the MongoDB container. Created on the first start. |
| `REDIS_PASSWORD` | Password of the Redis container. `REDIS_USERNAME` stays `default`. |
| `RABBITMQ_USER`, `RABBITMQ_PASS`, `RABBITMQ_ERLANG_COOKIE` | Credentials of the RabbitMQ container. Created on the first start. |
| `AI_PROVIDER` | `openai` or `gemini` (default `gemini`). |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI credentials and model (default `gpt-5-mini`). Required when `AI_PROVIDER=openai`. |
| `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | Vertex AI project and region. Only used when `AI_PROVIDER=gemini`. |
| `MERCADOPAGO_SECRET_KEY` | Mercado Pago access token. |
| `MERCADOPAGO_WEBHOOK_SECRET` | Mercado Pago webhook signature secret, from the same application as the access token. |
| `CORS_ORIGINS` | Comma-separated allowed origins. Empty allows all origins. |
| `API_DOMAIN` | Public domain of the API in production, for example `api.example.com`. |

Use long random values for the passwords and secrets, for example generated with `openssl rand -hex 24`. Since the MongoDB and Redis connection strings are built by Docker Compose, use hexadecimal passwords so they need no URL escaping.

Sensitive credentials should not be committed to the repository.

When the OpenAI key runs out of credits or is revoked, the worker stops retrying and marks the job as `failed` with the message `The briefing service is temporarily unavailable. Please try again later.`, so the client can submit the answers again once the account is fixed.

Firebase sign-in requires the Google service account credentials in the `.env` file. Vertex AI uses the same credentials when `AI_PROVIDER=gemini`.

The Google credentials JSON file is now generated dynamically when the application starts, so you do not need to manually place `google_credentials.json` inside the `config/` directory.

Add the required Google service account information to your `.env` file using the following environment variables:

```env
GOOGLE_TYPE=
GOOGLE_PROJECT_ID=
GOOGLE_PRIVATE_KEY_ID=
GOOGLE_PRIVATE_KEY=
GOOGLE_CLIENT_EMAIL=
GOOGLE_CLIENT_ID=
GOOGLE_AUTH_URI=
GOOGLE_TOKEN_URI=
GOOGLE_AUTH_PROVIDER_X509_CERT_URL=
GOOGLE_CLIENT_X509_CERT_URL=
GOOGLE_UNIVERSE_DOMAIN=
```

The application will use these environment variables to dynamically generate the Google credentials file during startup.

## Running the Application

Clone the repository and enter the project directory:

```sh
git clone https://github.com/id0ubl3g/misa-flask-api
cd misa-flask-api
```

Start the application and its dependencies with Docker Compose:

```sh
make run
```

This starts the API, the briefing worker, MongoDB, Redis and RabbitMQ. The API listens on `http://127.0.0.1:5000`, and the databases are only reachable inside the Docker network. Set the MongoDB, Redis and RabbitMQ credentials in `.env` before the first start, since the containers create their users from them.

Other useful commands:

| Command | Description |
| --- | --- |
| `make restart` | Rebuilds and restarts the API and the worker. |
| `make logs` | Follows the API and worker logs. |
| `make stop` | Stops all containers. Data is kept in Docker volumes. |
| `make backup` | Saves a compressed MongoDB dump in `backups/`. |

The briefing generation runs in the worker: `ping_client_response` and `pong_client_response` return `202` and the client polls `/misa/briefing/status/<token>` until `status` is `done` (or `failed`, in which case the answers can be submitted again).

To check the running containers:

```sh
docker compose ps
```

## Production Deployment

In production, everything runs on a single server with Docker Compose. Caddy sits in front of the API as a reverse proxy and issues the HTTPS certificate automatically.

1. Point a DNS `A` record for the API domain (for example `api.example.com`) to the server IP.
2. Open the HTTP and HTTPS ports on the server firewall:

   ```sh
   sudo ufw allow 22 && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
   ```

3. Clone the repository, copy the `.env` file to the server and set `API_DOMAIN` to the API domain.
4. Start the stack with the production profile, which also starts Caddy:

   ```sh
   make deploy
   curl https://api.example.com/health
   ```

5. In the Mercado Pago panel, set the webhook URL to `https://api.example.com/misa/webhook` with the payments event. The "Simulate notification" button should get a `400` (the simulated payment does not exist); a `401` means `MERCADOPAGO_WEBHOOK_SECRET` belongs to another application.
6. In the Firebase console, add the frontend domain under Authentication > Settings > Authorized domains.
7. Schedule a daily MongoDB backup with `crontab -e`, keeping the last 14 days:

   ```cron
   0 3 * * * cd ~/misa-flask-api && make backup && find backups -mtime +14 -delete
   ```

To update the server after new commits:

```sh
git pull && make deploy
```

## API Documentation

### Endpoints

| Method   | Endpoint                                      | Description                                                                             |
| -------- | --------------------------------------------- | --------------------------------------------------------------------------------------- |
| `GET`    | `/health`                                     | Checks the health and availability of the API.                                          |
| `POST`   | `/misa/briefing/create_client`                | Creates a client and initializes a brand briefing.                                      |
| `POST`   | `/misa/briefing/ping_client_response/<token>` | Queues the client's initial responses to generate personalized questions (returns 202). |
| `POST`   | `/misa/briefing/pong_client_response/<token>` | Queues the client's personalized responses to generate the brand briefing (returns 202). |
| `GET`    | `/misa/briefing/status/<token>`               | Returns the briefing job status and, when ready, the generated questions or briefing.   |
| `GET`    | `/misa/getall_client_responses`               | Returns all client responses belonging to the authenticated designer.                   |
| `GET`    | `/misa/get_client_response/<token>`           | Returns a specific client response using the client token.                              |
| `DELETE` | `/misa/delete_client_response/<token>`        | Deletes a client response using the client token.                                       |
| `POST`   | `/misa/auth/google`                           | Authenticates a user through Firebase Google Authentication.                            |
| `POST`   | `/misa/refresh_token`                         | Generates a new access token using a valid refresh token.                               |
| `POST`   | `/misa/logout`                                | Revokes the current access token and, when sent, the refresh token.                     |
| `GET`    | `/misa/profile`                               | Returns the authenticated user's profile.                                               |
| `GET`    | `/misa/payments`                              | Returns the payment history of the authenticated designer.                              |
| `DELETE` | `/misa/account`                               | Deletes the authenticated account and its clients (requires `confirm_email`).           |
| `POST`   | `/misa/checkout`                              | Creates a Mercado Pago checkout for the selected subscription plan.                     |
| `POST`   | `/misa/webhook`                               | Processes Mercado Pago payment notifications and updates the subscription status.       |

### Core Endpoints

#### Misa Create Client

- **URL**: `/misa/briefing/create_client`
- **Method**: `POST`
- **Description**: Creates a client and initializes a brand briefing.
- **Security**: Requires JWT Bearer token in Authorization header.

##### Request Body Create Client

* **Content-Type**: `application/json`
* **Request Fields**:
  * `name_project`: Name of the project.
    * Type: `String`
    * **Required**: Yes
    * **Example**: `Brand Identity Project`
  * `name_client`: Name of the client.
    * Type: `String`
    * **Required**: Yes
    * **Example**: `John Doe`
  * `email_client`: Client's email address.
    * Type: `String`
    * **Required**: Yes
    * **Example**: `john@example.com`

###### Example Request Create Client

```sh
curl -X POST "http://127.0.0.1:5000/misa/briefing/create_client" \
-H "Content-Type: application/json" \
-H "Authorization: Bearer {token}" \
-d '{
    "name_project": "Brand Identity Project",
    "name_client": "John Doe",
    "email_client": "john@example.com"
}'
```

### Example Use Case

#### Frontend Integration Create Client

```ts
const API_URL = import.meta.env.VITE_API_URL

interface CreateClientPayload {
  name_project: string
  name_client: string
  email_client: string
}

interface CreateClientResponse {
  message: string
  token: string
  usage: {
    current_count: number
    max_limit: number
    remaining: number
  }
}

export async function createClient(
  accessToken: string,
  payload: CreateClientPayload,
): Promise<CreateClientResponse> {
  const response = await fetch(`${API_URL}/misa/briefing/create_client`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  })

  const data = await response.json()

  if (!response.ok) {
    throw new Error(data.error)
  }

  return data
}

const { token } = await createClient(accessToken, {
  name_project: 'Brand Identity Project',
  name_client: 'John Doe',
  email_client: 'john@example.com',
})

const briefingLink = `${window.location.origin}/briefing/${token}`
```

#### Frontend Integration Briefing Flow

The client answers the briefing without logging in, using only the token from the link. Both submissions are processed by the worker, so the frontend sends the answers and then polls the status endpoint until the job is `done` or `failed`.

```ts
type BriefingStage = 'initial' | 'briefing'

interface BriefingStatus {
  token: string
  stage: BriefingStage | null
  status: 'queued' | 'processing' | 'done' | 'failed' | null
  initial_questions_completed: boolean
  questions_personalized_completed: boolean
  questions?: Record<'context_questions' | 'refinement_questions', Record<string, string>>
  briefing_data?: Record<string, unknown>
  error?: string
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function waitForBriefingJob(token: string, stage: BriefingStage): Promise<BriefingStatus> {
  const deadline = Date.now() + 5 * 60 * 1000

  while (Date.now() < deadline) {
    await wait(3000)

    const response = await fetch(`${API_URL}/misa/briefing/status/${token}`)
    const status: BriefingStatus = await response.json()

    if (status.stage !== stage) continue
    if (status.status === 'done') return status
    if (status.status === 'failed') throw new Error(status.error)
  }

  throw new Error('The briefing is taking longer than expected. Please try again later.')
}

async function submitBriefingJob(path: string, token: string, payload: object, stage: BriefingStage) {
  const response = await fetch(`${API_URL}${path}/${token}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok && response.status !== 409) {
    throw new Error((await response.json()).error)
  }

  return waitForBriefingJob(token, stage)
}

const { questions } = await submitBriefingJob('/misa/briefing/ping_client_response', token, {
  business: 'Specialty coffee shop focused on local producers.',
  target_audience: 'Young professionals who work near downtown.',
  objective: 'Build a brand that feels welcoming and premium.',
  differential: 'Beans roasted in house every morning.',
  personality: 'Warm, curious and close to the community.',
}, 'initial')

const { briefing_data } = await submitBriefingJob('/misa/briefing/pong_client_response', token, {
  context_questions: { 'question 1': '...', 'question 2': '...', 'question 3': '...', 'question 4': '...', 'question 5': '...' },
  refinement_questions: { 'question 1': '...', 'question 2': '...', 'question 3': '...', 'question 4': '...', 'question 5': '...' },
}, 'briefing')
```

Since the status endpoint always reflects the latest stage, the frontend can also call it when the briefing page opens to resume the client at the right step, for example after a page reload or when the link is opened on another device.

## Acknowledgments

This project was developed in collaboration with Toni and Ewerton. [Toni](https://github.com/ToniRoberto/WebScrapingPython) was responsible for the frontend development, contributing to the integration of the API with a modern and intuitive interface. [Ewerton](https://github.com/ewerton3000) was responsible for the project's data modeling, contributing to the organization and structure of the data required by the application.

## License

This project is licensed under the terms of the [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0). See the [LICENSE](./LICENSE) file for details.