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
* JWT-based authentication
* Client management
* MongoDB Atlas-based data persistence
* Redis caching and rate limiting
* Firebase authentication
* Google authentication
* Mercado Pago subscription integration
* Docker and Docker Compose support
* Metrics and client briefing statistics

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
    │   │   └── vertex_ai.py
    │   └── utils/
    │       ├── return_responses.py
    │       └── system_utils.py
    ├── .dockerignore
    ├── .env.example
    ├── .gitignore
    ├── docker-compose.yml
    ├── Dockerfile
    ├── LICENSE
    ├── README.md
    ├── requirements.txt
    ├── run.py
```

## Prerequisites

To run the Misa Flask API, use a Linux environment with Python 3.10 or higher. The environment must include Docker and Docker Compose for containerized services, as well as internet access for external services such as MongoDB Atlas, Firebase, Google Cloud, Mercado Pago, and generative AI services.

The application also requires:

* Docker
* Docker Compose
* Redis
* A MongoDB Atlas connection

### Install Docker

Follow the official Docker installation guide:

[https://docs.docker.com/engine/install/](https://docs.docker.com/engine/install/)

## Environment Configuration

Create the environment file from the provided example:

```sh
cp .env.example .env
```

Configure the required environment variables in `.env`, including:

* Flask secret keys
* JWT configuration
* MongoDB connection
* Redis configuration
* Google Cloud credentials
* Mercado Pago credentials
* Application base URLs

Sensitive credentials should not be committed to the repository.

To enable the Vertex AI and Firebase features, configure the Google Cloud service account credentials through the `.env` file.

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
docker compose up -d --build
```

To check the running containers:

```sh
docker compose ps
```

## API Documentation

### Endpoints

| Method   | Endpoint                                      | Description                                                                             |
| -------- | --------------------------------------------- | --------------------------------------------------------------------------------------- |
| `POST`   | `/misa/briefing/create_client`                | Creates a client and initializes a brand briefing.                                      |
| `POST`   | `/misa/briefing/ping_client_response/<token>` | Processes the client's initial briefing responses and generates personalized questions. |
| `POST`   | `/misa/briefing/pong_client_response/<token>` | Processes the client's personalized responses and generates the final brand briefing.   |
| `GET`    | `/misa/getall_client_responses`               | Returns all client responses belonging to the authenticated designer.                   |
| `GET`    | `/misa/get_client_response/<token>`           | Returns a specific client response using the client token.                              |
| `DELETE` | `/misa/delete_client_response/<token>`        | Deletes a client response using the client token.                                       |
| `POST`   | `/misa/auth/google`                           | Authenticates a user through Firebase Google Authentication.                            |
| `POST`   | `/misa/refresh_token`                         | Generates a new access token using a valid refresh token.                               |
| `GET`    | `/misa/profile`                               | Returns the authenticated user's profile.                                               |
| `GET`    | `/misa/metrics`                               | Returns client and briefing metrics for the authenticated designer.                     |
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

```

## Acknowledgments

This project was developed in collaboration with Toni and Ewerton. [Toni](https://github.com/ToniRoberto/WebScrapingPython) was responsible for the frontend development, contributing to the integration of the API with a modern and intuitive interface. [Ewerton](https://github.com/ewerton3000) was responsible for the project's data modeling, contributing to the organization and structure of the data required by the application.

## License

This project is licensed under the terms of the [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0). See the [LICENSE](./LICENSE) file for details.