"""Agregado Entrega: conduz uma Intent pelas etapas do SDLC até Maintain.

Cada método é um comando que valida a aresta no grafo de `TRANSICOES`; se recusa, levanta
`TransicaoInvalida` e o estado, o contador de ciclos e os eventos ficam intactos.
"""

from dataclasses import dataclass, field

from forja.domain.erros import CiclosEsgotados, IntentInvalida, TransicaoInvalida
from forja.domain.estados import LIMITE_PADRAO_DE_CICLOS, TRANSICOES, Estado, RaioDeImpacto
from forja.domain.eventos import (
    BandaViolada,
    EntregaConcluida,
    EventoDeDominio,
    PlanoPronto,
    PRAberto,
    SpecPronta,
)


@dataclass(slots=True)
class Entrega:
    intent_id: str
    ciclos_maximos: int = LIMITE_PADRAO_DE_CICLOS
    estado: Estado = Estado.PLAN
    ciclos_usados: int = 0
    aprovado_por: str | None = None
    _plano_publicado: bool = field(default=False, repr=False)
    _pr_aberto: bool = field(default=False, repr=False)
    _eventos: list[EventoDeDominio] = field(default_factory=lambda: [], repr=False)

    def __post_init__(self) -> None:
        if self.ciclos_maximos < 1:
            raise IntentInvalida("ciclos_maximos deve ser pelo menos 1")

    def _mover(self, destino: Estado, *, de: Estado | None = None) -> None:
        if de is not None and self.estado is not de:
            raise TransicaoInvalida(
                f"comando válido só em {de.value}, entrega está em {self.estado.value}"
            )
        if destino not in TRANSICOES[self.estado]:
            raise TransicaoInvalida(f"{self.estado.value} -> {destino.value} não é permitida")
        self.estado = destino

    def confirmar_intent(self) -> None:
        """Plan -> Design, com o intent.md confirmado por quem pediu."""
        self._mover(Estado.DESIGN, de=Estado.PLAN)

    def concluir_spec(self, pontos_em_aberto: int) -> None:
        """Design -> AguardandoSpec (há pontos em aberto) ou Build (spec fechada)."""
        if pontos_em_aberto < 0:
            raise IntentInvalida("pontos em aberto não pode ser negativo")
        if pontos_em_aberto > 0:
            self._mover(Estado.AGUARDANDO_SPEC, de=Estado.DESIGN)
            return
        self._mover(Estado.BUILD, de=Estado.DESIGN)
        self._eventos.append(SpecPronta(self.intent_id))

    def resolver_pontos_em_aberto(self) -> None:
        """AguardandoSpec -> Build, depois que um humano resolve os pontos."""
        self._mover(Estado.BUILD, de=Estado.AGUARDANDO_SPEC)
        self._eventos.append(SpecPronta(self.intent_id))

    def concluir_build(self) -> None:
        """Build -> Test, com plan.md e diff prontos."""
        self._mover(Estado.TEST, de=Estado.BUILD)
        if not self._plano_publicado:
            self._plano_publicado = True
            self._eventos.append(PlanoPronto(self.intent_id))

    def registrar_verificacao(self, *, verde: bool) -> None:
        """Test -> Review (verde) ou Test -> Build (falha, conta um ciclo até o limite)."""
        if self.estado is not Estado.TEST:
            raise TransicaoInvalida(f"verificação só em test, entrega está em {self.estado.value}")
        if verde:
            self._mover(Estado.REVIEW)
            if not self._pr_aberto:
                self._pr_aberto = True
                self._eventos.append(PRAberto(self.intent_id))
            return
        if self.ciclos_usados >= self.ciclos_maximos:
            raise CiclosEsgotados(
                f"{self.ciclos_usados} ciclos Test/Build já usados (máximo {self.ciclos_maximos})"
            )
        self._mover(Estado.BUILD)
        self.ciclos_usados += 1

    def concluir_review(
        self,
        *,
        achados_bloqueantes: bool,
        raio: RaioDeImpacto,
        politica_permite_deploy: bool = True,
    ) -> None:
        """Review -> Build (achados), AguardandoHumano (raio alto ou política nega) ou Deploy."""
        if self.estado is not Estado.REVIEW:
            raise TransicaoInvalida(f"review só em review, entrega está em {self.estado.value}")
        if achados_bloqueantes:
            self._mover(Estado.BUILD)
        elif raio is RaioDeImpacto.ALTO or not politica_permite_deploy:
            self._mover(Estado.AGUARDANDO_HUMANO)
        else:
            self._mover(Estado.DEPLOY)

    def aprovar(self, aprovador: str) -> None:
        """AguardandoHumano -> Deploy; guarda quem aprovou (trailer Approved-By)."""
        if not aprovador.strip():
            raise IntentInvalida("aprovação precisa de um aprovador identificado")
        self._mover(Estado.DEPLOY, de=Estado.AGUARDANDO_HUMANO)
        self.aprovado_por = aprovador

    def concluir_deploy(self) -> None:
        """Deploy -> Maintain."""
        self._mover(Estado.MAINTAIN, de=Estado.DEPLOY)
        self._eventos.append(EntregaConcluida(self.intent_id))

    def registrar_banda_violada(self, banda: str, evidencia: str, novo_intent_id: str) -> "Entrega":
        """Em Maintain, uma banda violada gera um novo intent.md: a próxima Entrega nasce em Plan.

        Esta Entrega continua em Maintain, que é terminal para ela.
        """
        if self.estado is not Estado.MAINTAIN:
            raise TransicaoInvalida(
                f"banda só é monitorada em maintain, entrega está em {self.estado.value}"
            )
        self._eventos.append(BandaViolada(self.intent_id, banda=banda, evidencia=evidencia))
        return Entrega(intent_id=novo_intent_id, ciclos_maximos=self.ciclos_maximos)

    def retirar_eventos(self) -> list[EventoDeDominio]:
        eventos, self._eventos = self._eventos, []
        return eventos
