import tellurium as te

r = te.loada("""
model and_gate()
  X1 := alpha
  X2 := beta
  
  -> LacI; ymin_LacI + X1 * (ymax_LacI - ymin_LacI)
  LacI -> ; LacI       
  ymin_LacI = 0.0034
  ymax_LacI = 2.8
             
  -> AraC; ymin_AraC + X2 * (ymax_AraC - ymin_AraC)
  AraC -> ; AraC    
  ymin_AraC = 0.0082
  ymax_AraC = 2.5
             
  -> A1_AmtR; kdyn * (ymin_A1_AmtR + (ymax_A1_AmtR - ymin_A1_AmtR)/(1 + (LacI/K_A1_AmtR)^n_A1_AmtR))
  A1_AmtR -> ; kdyn*A1_AmtR
  ymin_A1_AmtR = 0.06
  ymax_A1_AmtR = 3.8
  K_A1_AmtR = 0.07
  n_A1_AmtR = 1.6
             
  -> P2_PhlF; kdyn * (ymin_P2_PhlF + (ymax_P2_PhlF - ymin_P2_PhlF)/(1 + (AraC/K_P2_PhlF)^n_P2_PhlF))
  P2_PhlF -> ; kdyn*P2_PhlF
  ymin_P2_PhlF = 0.02
  ymax_P2_PhlF = 4.1
  K_P2_PhlF = 0.13
  n_P2_PhlF = 3.9
             
  -> S4_SrpR; kdyn * (ymin_S4_SrpR + (ymax_S4_SrpR - ymin_S4_SrpR)/(1 + ((A1_AmtR + P2_PhlF)/K_S4_SrpR)^n_S4_SrpR))
  S4_SrpR -> ; kdyn*S4_SrpR
  ymin_S4_SrpR = 0.007
  ymax_S4_SrpR = 2.1
  K_S4_SrpR = 0.1
  n_S4_SrpR = 2.8
             
  -> Y; c * S4_SrpR
  Y -> ; Y
  c = 0.4
             
  kdyn = 1
  alpha = 0
  beta = 0

  E1: at time > 10:
    alpha = 1
  E2: at time > 20:
    beta = 1
end
""")

result = r.simulate(0, 60, 400, ['time', 'X1', 'X2', 'Y'])
r.plot()