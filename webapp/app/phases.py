"""Phase modules (build-plan v2, P10 onwards). Each module registers what it brings when it is imported here:
its tables (db.register_schema), its job kinds (worker.register_job), its checkpoint kinds
(checkpoints.register_kind) and its routes (ROUTERS). main.py includes every router in ROUTERS.

One line per phase — keep the list alphabetical by phase so parallel branches merge cleanly."""
from . import checkpoints                     # P10: the checkpoint service and the Validation queue
from . import start, team                     # P10: Start from an idea or a plan; Team & agents
from . import rfp, studio                     # P11: Consulting studio - Proposals, decks & documents; RFP & bid response
from . import itsm                            # P12: Service desk (ITSM) - Jira / Freshservice triage, write-back after approval
from . import lineage, intan                  # P13: lineage & asset graph, Integration analytics
from . import observe                         # P14: Data observability
from . import migrate                         # P15: Migrate BI - Discover, Decide, Convert, Prove, Hand over, Run
from . import heal, sdlc                      # P16: Self-healing, AI SDLC
from . import tenancy                         # P17: tenants, partners and editions (platform console, access, hand-over)
from . import workbench, packs               # Module workbench: one engine for the wave modules' work types; app/packs/ holds one pack per module (pilot: quality)

ROUTERS = [checkpoints.router, start.router, team.router, studio.router, rfp.router, itsm.router, lineage.router, intan.router, observe.router, migrate.router,
           heal.router, sdlc.router, tenancy.router, workbench.router]
