"""Tuteur IA : trois modes (professeur, conversation libre, examinateur).

Deux moteurs :
- `LocalTutor` : hors ligne, toujours disponible (règles de correction locales,
  cours de grammaire et banque de sujets) ;
- `AnthropicEngine` : Claude, en ligne, si l'utilisateur l'a choisi et a
  enregistré sa clé API dans le coffre sécurisé du système.

En cas d'échec du moteur en ligne, le tuteur bascule sur le moteur local.
"""
from tcfmaster.services.ai.base import (MODE_CONVERSATION, MODE_EXAMINER, MODE_LABELS,
                                        MODE_TEACHER, MODES, AIUnavailable, Conversation,
                                        TutorReply, Turn)

__all__ = ["MODES", "MODE_LABELS", "MODE_TEACHER", "MODE_CONVERSATION", "MODE_EXAMINER",
           "AIUnavailable", "Conversation", "TutorReply", "Turn"]
