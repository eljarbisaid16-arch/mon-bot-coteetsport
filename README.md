# PariMatchia Bot

Bot Python (FastAPI + Selenium + undetected-chromedriver + 2captcha) qui :

1. **Scrape** les matchs et cotes de `coteetsport.ma` (avec leurs `data-selection-id` cachés)
2. **Exécute** un ticket : ouvre Chrome en arrière-plan, clique sur les sélections demandées par l'app,
   saisit la mise, déclenche la génération du code-barres, capture l'image et la renvoie en base64.

## Déploiement Railway

1. Pousser ce dossier sur un repo GitHub.
2. Sur [railway.app](https://railway.app) → **New Project → Deploy from GitHub** → sélectionner le repo.
3. Railway détecte le `Dockerfile` et build automatiquement.
4. Ajouter les variables d'environnement (onglet **Variables**) :
   - `API_TOKEN` → une longue chaîne aléatoire
   - `CAPTCHA_API_KEY` → votre clé 2captcha
5. Une fois déployé, copier l'URL publique (ex: `https://parimatchia-bot.up.railway.app`).
6. Coller cette URL + le `API_TOKEN` dans la page **Bot Setup** de l'app PariMatchia.

## Endpoints

| Méthode | Path             | Description                                 |
|---------|------------------|---------------------------------------------|
| GET     | `/health`        | Healthcheck                                 |
| GET     | `/matches`       | Liste des matchs scrapés                    |
| POST    | `/place-ticket`  | Body: `{ "ids": ["123_1"], "mise": "50" }` |

Tous les endpoints (sauf `/health`) requièrent l'en-tête : `Authorization: Bearer <API_TOKEN>`.

## Adapter les sélecteurs

`scraper.py` et `executor.py` contiennent des sélecteurs CSS génériques (`[data-match]`,
`[data-selection-id]`, `button.generate-barcode`, etc.). Le DOM réel de coteetsport.ma
change régulièrement : ouvrez le site dans Chrome → Inspect, puis ajustez les sélecteurs
dans ces deux fichiers.

## Avertissement légal

Le scraping et l'automatisation de paris sportifs peuvent enfreindre les CGU du site
et la réglementation locale. Vous êtes seul responsable de l'usage de ce bot.
