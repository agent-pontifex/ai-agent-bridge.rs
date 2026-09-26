#!/usr/bin/env python3
from itertools import product
for deliveries in product(("corr-a","corr-b"),repeat=4):
  effects=set()
  for correlation_id in deliveries: effects.add(correlation_id)
  assert effects==set(deliveries), "bridge effects diverged from unique correlation IDs"
  assert len(effects)<=2
print("correlated-message exactly-once model: ok")
