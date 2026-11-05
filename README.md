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

## Sans abonnement API : import des CSV TopstepX

### Exporter depuis TopstepX (à faire pour chaque compte)

1. Connecte-toi sur TopstepX.
2. Sélectionne le compte en haut de la plateforme, dans le sélecteur de compte.
3. En bas de l'écran, ouvre l'onglet **Trades**. Ne prends pas Orders : Trades contient le P&L de chaque trade.
4. Clique sur **Export**. Il peut se trouver dans un menu « ⋯ » ou s'afficher avec un clic droit sur le tableau.
5. Choisis la période : les 6 derniers mois, ou depuis l'ouverture du compte.
6. Enregistre le fichier sous le **nom du compte**, par exemple `50KTC-V2-12345.csv`. Ce nom sert à identifier le compte dans le journal.

Comptes clôturés : coche **« Show Closed Accounts »** dans le sélecteur de compte ou dans l'onglet Accounts du tableau de bord Topstep, puis refais les mêmes étapes. Si l'export n'est pas proposé pour un compte fermé, demande l'historique au support Topstep.

### Autres prop firms (Lucid Trading, etc.)

L'import reconnaît aussi :
- le rapport **Performance de Tradovate** (colonnes `buyFillId`, `boughtTimestamp`, `pnl`…). Le sens long ou short est déduit de l'ordre achat/vente ;
- l'onglet **Trades de NinjaTrader 8** (colonnes `Trade number`, `Market pos.`, `Profit`…).

Nomme les fichiers avec un préfixe de firme, par exemple `LUCID-123456.csv`, pour distinguer les comptes dans le journal. Le rapport Tradovate ne contient pas les frais, donc le P&L y est brut.

### Importer

Mets tous les CSV dans un dossier, par exemple `exports/`, puis lance :

```bash
python -m tradingcoach import-csv exports/
python -m tradingcoach import-csv autre_fichier.csv --account "NOM-DU-COMPTE"
```

Résultat : `data/trades_csv.csv`, avec un trade complet (entrée et sortie) par ligne, tous comptes confondus, et le P&L net des frais. On peut relancer l'import autant de fois que nécessaire : les doublons sont ignorés.

Les colonnes sont reconnues par leur nom (Id, ContractName, EnteredAt, ExitedAt, PnL, Fees, Size, Type…). Si un fichier n'est pas reconnu, la commande affiche les colonnes trouvées : envoie-les-moi pour que j'adapte l'import.

## Tests

```bash
python -m unittest discover -s tests
```

Les tests utilisent un faux serveur local. Ils n'ont besoin d'aucun identifiant.
