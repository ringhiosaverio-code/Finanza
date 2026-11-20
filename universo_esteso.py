"""L'universo allargato della rete del medio periodo: più esempi da cui imparare (Nasdaq 100, grandi azioni europee,
ETF di settore e di fattore quotati a Milano). Solo i titoli con abbastanza storia su Yahoo vengono usati.

I titoli sono quelli negli indici oggi: chi ne è uscito manca, quindi il passato è un po' più bello di com'era.
"""

# Nasdaq 100 senza quelli già nell'S&P 100 dell'app
NASDAQ = ["ADI", "ADP", "ADSK", "AEP", "AMAT", "APP", "ARM", "ASML", "AXON", "AZN", "BIIB", "BKR", "CCEP", "CDNS", "CDW", "CEG",
          "CPRT", "CRWD", "CSGP", "CSX", "CTAS", "CTSH", "DASH", "DDOG", "DXCM", "EA", "EXC", "FANG", "FAST", "FTNT", "GEHC",
          "GFS", "IDXX", "KDP", "KLAC", "LRCX", "LULU", "MAR", "MCHP", "MDB", "MELI", "MNST", "MRVL", "MU", "NXPI", "ODFL",
          "ON", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "REGN", "ROP", "ROST", "SNPS", "TEAM", "TTD", "TTWO", "VRSK", "VRTX",
          "WBD", "WDAY", "XEL", "ZS", "ABNB", "SHOP", "MSTR"]

# grandi azioni europee (Euro Stoxx 50 e le più grandi dello STOXX 600), senza quelle italiane già nell'app
EUROPA = ["ASML.AS", "SAP.DE", "MC.PA", "SIE.DE", "TTE.PA", "SAN.PA", "OR.PA", "ALV.DE", "AIR.PA", "SU.PA", "IBE.MC", "DTE.DE",
          "BNP.PA", "SAN.MC", "CS.PA", "RMS.PA", "EL.PA", "AI.PA", "MUV2.DE", "ITX.MC", "DG.PA", "BAS.DE", "MBG.DE", "BMW.DE",
          "IFX.DE", "ADS.DE", "SAF.PA", "INGA.AS", "BBVA.MC", "NOKIA.HE", "ABI.BR", "KER.PA", "PRX.AS", "AD.AS", "DB1.DE",
          "VOW3.DE", "BAYN.DE", "RI.PA", "ORA.PA", "ENGI.PA", "VIE.PA", "CAP.PA", "SGO.PA", "GLE.PA", "ACA.PA", "BN.PA",
          "HO.PA", "DSY.PA", "RHM.DE", "SHL.DE", "HEN3.DE", "DHL.DE", "ENR.DE", "ADYEN.AS", "HEIA.AS", "PHIA.AS", "TEF.MC",
          "REP.MC", "AENA.MC", "SHEL.L", "AZN.L", "HSBA.L", "ULVR.L", "BP.L", "GSK.L", "RIO.L", "REL.L", "DGE.L", "BATS.L",
          "LSEG.L", "NG.L", "GLEN.L", "BARC.L", "LLOY.L", "VOD.L", "RR.L", "BA.L", "NESN.SW", "NOVN.SW", "ROG.SW", "UBSG.SW",
          "ZURN.SW", "ABBN.SW", "CFR.SW", "NOVO-B.CO", "VOLV-B.ST", "ERIC-B.ST", "ATCO-A.ST", "ASSA-B.ST"]

# ETF di settore, di fattore e di area quotati a Milano (verificati su Yahoo con almeno un anno e mezzo di storia)
ETF = ["VWCE.MI", "VUSA.MI", "XDWD.MI", "XDWT.MI", "XDWH.MI", "XDWF.MI", "XDWI.MI", "XDWC.MI", "XDWS.MI", "XDW0.MI",
       "XDWU.MI", "XDWM.MI", "INRG.MI", "GDX.MI", "SMH.MI", "ISAC.MI", "XDEV.MI", "XDEM.MI", "IWQU.MI", "IWMO.MI",
       "MVOL.MI", "EXSA.MI", "IUSA.MI", "CSCA.MI", "XMEU.MI", "VEUR.MI"]
