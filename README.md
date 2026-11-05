# Trading Coach

Récupère l'historique de tes trades sur **tous tes comptes TopstepX**, y compris les comptes inactifs ou clôturés, via l'API officielle TopstepX (ProjectX Gateway). Le but est d'en faire un journal de trading.

Il faut seulement Python 3.10 ou plus récent. Aucune dépendance à installer.

## 1. Obtenir ta clé API TopstepX

1. Souscris à l'accès API (abonnement payant chez Topstep, dans les paramètres ou la marketplace TopstepX).
2. Dans **TopstepX → Settings → API**, génère une **clé API** et copie-la.
3. Note ton **nom d'utilisateur TopstepX**. C'est ton identifiant de connexion, pas ton e-mail, sauf si c'est le même.

## 2. Configurer

```bash
cp .env.example .env
# puis édite .env :
# TOPSTEPX_USERNAME=...
# TOPSTEPX_API_KEY=...
```

Le fichier `.env` est ignoré par git. **Ne partage jamais ta clé API.**

## 3. Utiliser

```bash
python -m tradingcoach check      # teste la connexion
python -m tradingcoach accounts   # liste tous les comptes (actifs + inactifs)
python -m tradingcoach export     # exporte les 6 derniers mois
python -m tradingcoach export --months 3 --out data
```

L'export produit :

| Fichier | Contenu |
|---|---|
| `data/trades.csv` | toutes les exécutions, tous comptes confondus : date, contrat, sens, taille, prix, P&L, frais |
| `data/accounts.csv` | récap par compte : nombre d'exécutions, P&L réalisé, statut (`ok` ou erreur) |
| `data/raw/trades_<id>.json` | réponses brutes de l'API, pour vérification |

Le P&L n'est renseigné que sur l'exécution qui clôture la position. Il est vide sur l'exécution d'ouverture.

## Comptes clôturés

L'export demande tous les comptes (`onlyActiveAccounts: false`) puis tente de récupérer les trades de chacun. Si l'API refuse l'accès à un ancien compte, la colonne `status` de `accounts.csv` l'indique (par exemple `AccountNotFound`). Pour ces comptes, il faut passer par l'export CSV du tableau de bord Topstep (« Show Closed Accounts ») ou par le support.

## Tests

```bash
python -m unittest discover -s tests
```

Les tests utilisent un faux serveur local. Ils n'ont besoin d'aucun identifiant.
