"""Eventos de domínio dos contextos Intake, Delivery e Operations (design doc, seção 4.1)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EventoDeDominio:
    intent_id: str


@dataclass(frozen=True, slots=True)
class IntentRecebida(EventoDeDominio):
    origem: str


@dataclass(frozen=True, slots=True)
class IntentConfirmada(EventoDeDominio):
    confirmado_por: str


@dataclass(frozen=True, slots=True)
class SpecPronta(EventoDeDominio):
    pass


@dataclass(frozen=True, slots=True)
class PlanoPronto(EventoDeDominio):
    pass


@dataclass(frozen=True, slots=True)
class PRAberto(EventoDeDominio):
    pass


@dataclass(frozen=True, slots=True)
class EntregaConcluida(EventoDeDominio):
    pass


@dataclass(frozen=True, slots=True)
class BandaViolada(EventoDeDominio):
    banda: str
    evidencia: str
