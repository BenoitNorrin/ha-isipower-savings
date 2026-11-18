# Isipower Savings

Estimer les économies de son installation solaire dans Home Assistant, avec des **barres par jour, par mois et par année**.

L’intégration utilise les puissances déjà disponibles dans Home Assistant. Elle ne demande ni compte Linky, ni token fournisseur. Elle fonctionne avec Isypower Cloud, et avec d’autres sources fournissant les mêmes mesures en W ou kW.

**Première version publique expérimentale.** Les résultats sont des estimations fondées sur des relevés espacés. Ils servent à suivre un gain dans le temps, pas à reproduire une facture au centime près.

## Fonctionnalités

- Tarif unique, ou heures pleines / heures creuses.
- Heures super creuses facultatives, avec leur propre prix.
- Plusieurs plages quotidiennes, y compris des plages qui traversent minuit.
- Sans injection prévue, injection gratuite ou injection rémunérée.
- Choix des entités dans l’interface, avec des textes d’aide et des noms indicatifs.
- Consommations supplémentaires facultatives : une borne de recharge n’est pas nécessaire.
- Conservation des relevés **et des changements de tarifs** dans des fichiers locaux.
- Reprise des calculs après redémarrage, sans changer les anciens prix.
- Aucune commande envoyée à l’onduleur, à la batterie ou au compteur.

## Prérequis

- Home Assistant **2026.11.2 ou ultérieur**.
- Un capteur de **puissance consommée** en W ou kW.
- Un capteur de **puissance réseau** en W ou kW.

La consommation doit représenter les usages que l’on aurait conservés sans panneaux ni batterie. La recharge de la batterie ne doit donc pas être incluse dans ce capteur. En revanche, les achats réseau comprennent bien la recharge éventuelle de la batterie.

La consommation de la voiture peut déjà être incluse dans la mesure principale. Si elle est mesurée séparément et manque à cette mesure, on peut l’ajouter. **Ne pas ajouter deux fois une consommation.**

### Quel capteur réseau choisir ?

Deux configurations sont acceptées :

| Configuration | Réglage |
| --- | --- |
| Un capteur signé : positif à l’import, négatif à l’injection | Choisir uniquement la puissance réseau. |
| Deux capteurs positifs distincts : import et injection | Choisir la puissance réseau d’import et le capteur d’injection facultatif. |

Si le capteur signé utilise la convention opposée, l’option avancée **Inverser le signe du réseau** permet de l’adapter.

## Installation

### Avec HACS, comme dépôt personnalisé

1. Ajouter `https://github.com/BenoitNorrin/ha-isipower-savings` aux dépôts personnalisés HACS, catégorie **Intégration**.
2. Télécharger **Isipower Savings**.
3. Redémarrer Home Assistant.
4. Dans **Paramètres → Appareils et services → Ajouter une intégration**, chercher **Isipower Savings**.

Le dépôt est prévu pour l’installation comme dépôt personnalisé ; il n’est pas annoncé comme inclus dans le catalogue officiel HACS.

### Installation manuelle

1. Copier `custom_components/isipower_savings` dans `/config/custom_components/isipower_savings`.
2. Redémarrer Home Assistant.
3. Ajouter **Isipower Savings** dans Appareils et services.

La configuration se fait ensuite dans l’interface. Aucun package YAML, assistant de prix ou script externe n’est nécessaire.

## Configuration

### 1. Mesures

Choisir la consommation principale et le réseau. Tous les autres capteurs sont facultatifs.

Les textes d’aide affichent des exemples **indicatifs**, sans sélectionner d’entité à votre place :

| Champ | Exemple possible avec Isypower |
| --- | --- |
| Consommation principale | `sensor.izypower_cloud_<centrale>_consommation` |
| Réseau | `sensor.izypower_cloud_<centrale>_puissance_reseau` |
| Consommation supplémentaire | Une borne ou un autre usage exclu de la consommation principale. |
| Horodatage de la source | `sensor.izypower_cloud_<centrale>_derniere_mise_a_jour` |

L’horodatage aide à reconnaître plusieurs mises à jour d’un même rapport cloud. Sans ce capteur, l’intégration échantillonne les états disponibles dans Home Assistant.

La devise et le fuseau sont ceux choisis lors de la création du suivi. Ils restent fixes pour ne pas mélanger les historiques.

### 2. Tarifs d’achat

Les prix sont saisis **par kWh**, dans la devise configurée.

- **Tarif unique** : saisir le prix de base et laisser HC et heures super creuses désactivées.
- **HP/HC** : le prix de base est celui des heures pleines ; activer les heures creuses et renseigner leur prix et leurs plages.
- **Heures super creuses** : activer leur option et renseigner leur prix et leurs plages. Elles peuvent être utilisées avec ou sans heures creuses ordinaires.

Format d’une ou plusieurs plages :

```text
22:00-06:00,13:00-15:00
```

Une plage traversant minuit est acceptée. `00:00-24:00` représente une journée entière. Les horaires s’appliquent chaque jour ; les calendriers variables selon les jours, Tempo et les prix dynamiques ne sont pas gérés dans cette version.

**En cas de chevauchement, les heures super creuses sont prioritaires sur les heures creuses.** En dehors de ces plages, le tarif de base s’applique.

### 3. Injection et revente

| Mode | Énergie injectée enregistrée | Recette calculée |
| --- | --- | --- |
| Sans injection prévue | Oui, si une injection est mesurée | Non |
| Injection gratuite | Oui | Non |
| Injection rémunérée | Oui | kWh injectés × tarif de rachat |

Le prix de rachat est indépendant du prix d’achat. Une injection gratuite n’est jamais valorisée au tarif de l’électricité achetée. Ces choix décrivent le calcul ; ils n’activent ni ne désactivent physiquement l’injection.

## Comment le gain est calculé

Pour chaque intervalle entre deux relevés, les puissances sont converties en kWh par interpolation. Le calcul est découpé à minuit, aux changements de tarif et aux limites des plages horaires.

```text
Coût sans installation = consommation des usages × tarif d’achat
Coût des achats = énergie importée × tarif d’achat
Économies sur les usages = coût sans installation − coût des achats
Revenus d’injection = énergie injectée × tarif de rachat, si rémunérée
Gain total = économies sur les usages + revenus d’injection
```

Les économies et les revenus sont conservés séparément. Les résultats négatifs restent négatifs : par exemple, une batterie chargée sur le réseau aujourd’hui pour être utilisée demain peut produire un gain négatif aujourd’hui.

Les frais d’abonnement, l’achat du matériel, son amortissement et d’éventuels frais contractuels ne sont pas inclus. Le scénario sans installation conserve les mêmes usages et les mêmes horaires.

## Dashboard

Le fichier [`examples/dashboard.yaml`](examples/dashboard.yaml) contient trois vues avec un graphique en barres du gain : **Jour**, **Mois** et **Année**.

Chaque barre correspond à la somme des intervalles effectivement mesurés. Aujourd’hui est inclus. Les périodes incomplètes restent partielles ; elles n’attendent pas une validation Linky.

Les statistiques disponibles sont :

| Identifiant | Contenu |
| --- | --- |
| `isipower_savings:benefit` | Gain total : économies + revenus d’injection. |
| `isipower_savings:savings` | Économies sur la consommation seulement. |
| `isipower_savings:revenue` | Revenus d’injection seulement. |
| `isipower_savings:with_installation` | Achats moins revenus d’injection. |
| `isipower_savings:without_installation` | Coût estimé des usages sans installation. |

Les capteurs `sensor.isipower_savings_jour`, `_mois` et `_annee` exposent le gain de la période en cours, avec le détail des coûts et des heures mesurées dans leurs attributs. Les identifiants peuvent varier si vous les renommez dans Home Assistant.

## Historique et évolution des tarifs

Les fichiers sont conservés dans :

```text
/config/isipower_savings/history-AAAA-MM.jsonl
```

Chaque ligne décrit un début de suivi, une mesure normalisée, un changement de sources ou un **changement de tarif horodaté**. Les prix, plages et conditions de revente sont enregistrés intégralement.

Pour changer un tarif, ouvrir **Configurer** sur l’intégration. Le changement s’applique à partir de sa prise en compte, sans réécrire les prix des anciennes périodes. Le redémarrage relit les mêmes fichiers et retrouve les mêmes résultats.

Sauvegarder ce dossier avec Home Assistant. Les journaux restent en dehors du dossier de l’intégration et survivent à une mise à jour HACS. Ils ne sont pas effacés lorsque l’intégration est retirée. Aucun fichier de mesures personnel n’est inclus dans ce dépôt.

## Qualité des mesures

Une puissance inconnue ne vaut pas zéro. Par défaut, les rapports de plus de 15 minutes et les intervalles de plus de 15 minutes sont ignorés. Les autres intervalles de la journée restent utilisables.

Les options avancées permettent d’ajuster ces limites. Une fraîcheur maximale de `0` désactive le contrôle d’âge, pour les sources qui ne publient que lorsque la valeur change. Cela ne désactive pas le contrôle des interruptions entre mesures.

Les changements d’heure sont pris en compte dans le fuseau configuré, y compris les fenêtres répétées ou inexistantes. Les écarts liés à la fréquence ou à la justesse des capteurs restent ceux d’une estimation.

## Passage depuis la version privée « économies solaires 2.0 »

Retirer l’ancien package `cout_solaire.yaml` avant d’activer cette intégration publique. Les intégrations portent des domaines différents : `economies_solaires` pour la version privée, `isipower_savings` pour celle-ci.

Le nouveau suivi démarre à son activation. Les anciens journaux restent conservés et ne sont pas importés automatiquement. L’intégration Isypower Cloud qui fournit les puissances reste nécessaire si elle est votre source.

## Tests et contributions

La CI GitHub Actions s’exécute sur chaque push et pull request :

- tests du calcul, des tarifs et de la relecture des fichiers ;
- tests des parcours Home Assistant de configuration et d’options ;
- vérification des fichiers JSON, de la syntaxe et du style ;
- validation de l’intégration et de sa structure HACS.

Les tests n’ont besoin d’aucun compte Isypower, Linky ou fournisseur. Ils utilisent des entités et des données fictives. Les journaux de tests restent temporaires.

Les tests du moteur peuvent également être lancés sans installer Home Assistant :

```sh
python -m unittest discover -s tests/unit -v
```

Pour exécuter toute la suite, utiliser Python 3.14 et installer `requirements_test.txt`, puis lancer `pytest`.

Les signalements et contributions sont bienvenus. Merci de retirer les données personnelles et les identifiants sensibles des extraits de journaux partagés.

## Licence

Copyright © 2026 BenoitNorrin. Projet distribué sous **GPL-3.0-only** ; voir [`LICENSE`](LICENSE).

Projet communautaire indépendant, sans affiliation officielle avec Isypower.
