# AdelineTarot — Site complet (Astrologie + Tarot en visio)

Site web complet en **espagnol** où les clients saisissent leur date, nom et
lieu de naissance, paient par **PayPal** (100 MXN ou 20 PEN à `@adelinetarot`)
et reçoivent un **lien de visioconférence unique**. Côté admin, **AdelineTarot**
accède à la carte natale et à un **rapport détaillé généré automatiquement**,
avec le même lien visio.

## Architecture

```
AdelineTarot/
├─ index.html              Landing + formulaire + paiement + confirmation (ES)
├─ admin.html              Panneau privé d'AdelineTarot
├─ assets/
│  ├─ styles.css           Thème mystique (nuit étoilée + or)
│  ├─ app.js               Logique client (réservation, PayPal, lien visio)
│  └─ admin.js             Logique admin (liste, carte natale, rapport)
└─ backend/
   ├─ app/
   │  ├─ main.py           App FastAPI + hébergement statique
   │  ├─ config.py         Réglages (prefixe ADELINE_)
   │  ├─ database.py       SQLAlchemy 2.0 (SQLite par défaut)
   │  ├─ models.py         Modèle Booking
   │  ├─ schemas.py        Validation Pydantic v2 (extra=forbid, honeypot)
   │  ├─ security.py       Headers, rate-limit, taille body, auth admin
   │  ├─ astrology.py      Carte natale (Soleil/Lune/Asc/planètes) + tarot
   │  ├─ report.py         Générateur du rapport détaillé (l'« IA »)
   │  └─ routers/
   │     ├─ bookings.py    POST création, POST paiement, GET statut
   │     └─ admin.py       GET liste / détail (carte + rapport), protégé
   ├─ requirements.txt
   ├─ .env.example
   └─ run.ps1
```

## Lancer en local (Windows / PowerShell)

```powershell
cd "AdelineTarot\backend"
& "..\..\.venv\Scripts\python.exe" -m pip install -r requirements.txt
.\run.ps1
```

Puis ouvrir **http://127.0.0.1:8000** (site) et **http://127.0.0.1:8000/admin**
(panneau). La doc API est sur `/api/docs`.

> La **clé admin** s'affiche dans la console au démarrage (ou définissez
> `ADELINE_ADMIN_TOKEN` dans `backend/.env`).

## Parcours utilisateur

1. Le client remplit nom, date, heure (optionnelle) et lieu de naissance, choisit
   le plan (100 MXN ou 20 PEN) → `POST /api/bookings` (tarif **autoritatif** côté
   serveur, jamais celui du client).
2. Paiement PayPal : boutons intégrés (si `ADELINE_PAYPAL_CLIENT_ID` est défini)
   **ou** lien **PayPal.Me** `paypal.me/adelinetarot/…` + bouton « Ya pagué ».
3. À la confirmation (`POST /api/bookings/{token}/pay`) le serveur génère :
   - la **carte natale** + une **tirage de tarot** (reproductible),
   - un **rapport détaillé** en espagnol,
   - une **salle Jitsi unique** `https://meet.jit.si/AdelineTarot-…` (aucune clé API).
4. Le client obtient le lien visio ; **AdelineTarot** voit la même salle + la
   carte natale + le rapport dans `/admin`.

## Configuration PayPal

- **Intégré** : copiez votre `client-id` PayPal (live ou sandbox) dans
  `ADELINE_PAYPAL_CLIENT_ID`. Les boutons se chargent automatiquement.
- **PayPal.Me** : `ADELINE_PAYPAL_ME_HANDLE=adelinetarot` (par défaut).
- PayPal ne règle pas en **PEN** : le plan soles est débité de son équivalent
  **USD** (`ADELINE_PRICE_PEN_AS_USD`). Le plan pesos est débité en **MXN**.

### ⚠️ Note production (paiement)
Dans cette version, l'ordre PayPal est créé/capturé côté client et confirmé via
`/pay`. Pour une boutique réelle, créez et **capturez l'ordre côté serveur**
avec l'API REST PayPal (et un **webhook**) avant de marquer `paid`, afin de
vérifier réellement l'encaissement. Le montant stocké reste toujours celui
calculé par le serveur.

## Sécurité (OWASP)

- **A01** : accès admin protégé par jeton à comparaison constante (`compare_digest`).
- **A03** : ORM paramétré (anti-SQLi) ; sorties échappées côté admin (anti-XSS) ;
  CSP stricte.
- **A04** : rate-limiting par IP, limite de taille du body, honeypot anti-bot.
- **A05** : en-têtes durcis (nosniff, X-Frame-Options, Referrer-Policy, HSTS hors debug).
- Aucune donnée de carte n'est stockée (PayPal gère la transaction).

## Notes astrologiques
Les positions (Lune, planètes, Ascendant) sont des **approximations** symboliques
(longitudes moyennes) pensées pour la consultation ; le Soleil utilise le zodiaque
calendaire tropical exact. L'heure de naissance affine l'Ascendant.
