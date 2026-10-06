# CareBot

CareBot is a doctor-assisted medical chatbot built with Python, Flask, Tailwind CSS, Bootstrap, and the Groq API. It is designed to provide general health guidance, basic symptom support, and safe over-the-counter (OTC) suggestions while reinforcing that it is not a replacement for professional medical care.

## Features

- Flask backend with REST API for chat interactions
- Groq-powered medical assistant using `openai/gpt-oss-120b`
- Modern, professional UI using Bootstrap and Tailwind CDN
- Safety-first behavior for emergency detection and restricted medication handling
- Conversation continuity with session-based chat history
- Safe general guidance for common symptoms and OTC remedies
- Clear medical disclaimers and escalation to licensed professionals

## Tech Stack

- Python 3.10+
- Flask
- Groq API
- Tailwind CSS CDN
- Bootstrap 5 CDN
- JavaScript (AJAX/fetch)

## Project Structure

```bash
carebot/
├── app.py
├── requirements.txt
├── vercel.json
├── .env.example
├── .gitignore
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── app.js
├── templates/
│   └── index.html
├── README.md
└── .venv/