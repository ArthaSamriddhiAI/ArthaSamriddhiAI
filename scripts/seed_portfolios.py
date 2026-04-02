#!/usr/bin/env python3
"""Seed realistic HNI portfolios for all 6 investors."""

import json
import sys
import urllib.request

BASE = "http://13.204.187.25/api/v1"


def get(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def post_csv(path, csv_content):
    import email.generator
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="portfolio.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n"
        f"{csv_content}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


# Portfolio definitions per investor name
PORTFOLIOS = {
    "Dr. Sunita Reddy": """asset_class,symbol_or_id,description,quantity,acquisition_date,acquisition_price,current_price,notes
fd,SBI_FD_1YR,SBI Fixed Deposit 1 Year,4000000,2025-01-15,1.00,1.00,7.1% p.a.
fd,HDFC_FD_2YR,HDFC Bank FD 2 Year,3000000,2024-06-01,1.00,1.00,7.25% p.a.
fd,ICICI_FD_3YR,ICICI Bank FD 3 Year,2500000,2024-01-10,1.00,1.00,7.0% p.a.
fd,SBI_FD_5YR,SBI Fixed Deposit 5 Year (Tax Saver),1500000,2023-03-15,1.00,1.00,6.5% under 80C
mutual_fund,119819,SBI Magnum Gilt Fund - Growth,25000,2023-01-10,48.00,,Govt securities exposure
mutual_fund,100471,HDFC Short Term Debt Fund - Growth,40000,2022-06-15,28.50,,Short duration debt
mutual_fund,120716,UTI Nifty 50 Index Fund - Growth,20000,2023-04-01,120.00,,Index exposure
mutual_fund,100475,HDFC Balanced Advantage Fund - Growth,15000,2022-03-20,310.00,,Dynamic allocation
equity,HDFCBANK,HDFC Bank Ltd,200,2021-06-15,1480.00,,Banking blue-chip
equity,TCS,Tata Consultancy Services,50,2022-01-10,3600.00,,IT anchor
equity,INFY,Infosys Ltd,80,2022-03-15,1700.00,,IT diversification
equity,ITC,ITC Ltd,500,2021-09-01,210.00,,Dividend play
equity,HINDUNILVR,Hindustan Unilever Ltd,40,2023-01-20,2550.00,,Consumer staple
gold,GOLD_PHYSICAL,Physical Gold 24K (grams),100,2019-04-15,3200.00,7200.00,100 grams
gold,SGB_2025,Sovereign Gold Bond 2025-26,50,2020-10-01,5000.00,7100.00,50 units SGB
ppf,PPF_ACCOUNT,PPF Account (cumulative),3500000,2015-01-01,1.00,1.00,15 year lock-in
insurance,LIC_JEEVAN_ANAND,LIC Jeevan Anand Policy,1,2016-01-01,800000.00,1200000.00,Sum assured 20L
real_estate,PROP_HYD_01,2BHK Jubilee Hills Hyderabad,1,2017-06-01,8500000.00,14000000.00,Residential""",

    "Mr. Vikram Mehta": """asset_class,symbol_or_id,description,quantity,acquisition_date,acquisition_price,current_price,notes
equity,RELIANCE,Reliance Industries Ltd,300,2021-03-15,2050.00,,Core holding
equity,TCS,Tata Consultancy Services,120,2022-01-10,3400.00,,IT anchor
equity,HDFCBANK,HDFC Bank Ltd,400,2021-06-20,1400.00,,Banking
equity,INFY,Infosys Ltd,200,2022-04-01,1650.00,,IT
equity,BHARTIARTL,Bharti Airtel Ltd,300,2022-09-15,780.00,,Telecom
equity,SBIN,State Bank of India,500,2023-01-10,580.00,,PSU Banking
equity,LT,Larsen & Toubro Ltd,100,2022-06-01,1800.00,,Infrastructure
equity,KOTAKBANK,Kotak Mahindra Bank,150,2023-03-01,1750.00,,Private banking
equity,BAJFINANCE,Bajaj Finance Ltd,60,2022-11-01,6800.00,,NBFC
equity,TITAN,Titan Company Ltd,80,2023-06-01,2800.00,,Consumer discretionary
mutual_fund,119598,SBI Blue Chip Fund - Growth,8000,2021-01-15,52.00,,Large cap core
mutual_fund,100356,Mirae Asset Large Cap Fund - Growth,5000,2022-04-01,78.00,,Large cap
mutual_fund,102885,Kotak Flexicap Fund - Growth,6000,2022-07-01,55.00,,Flexi cap
mutual_fund,119816,Axis Midcap Fund - Growth,4000,2023-01-10,72.00,,Mid cap exposure
mutual_fund,100173,Axis Long Term Equity Fund - Growth,10000,2022-03-20,68.00,,ELSS tax saver
fd,SBI_FD_1YR,SBI Fixed Deposit 1 Year,3000000,2025-04-01,1.00,1.00,7.1% p.a.
bond,HDFC_NCD_2028,HDFC Ltd NCD 8.5% 2028,200,2024-01-15,1000.00,1020.00,Face value 1000
bond,NHAI_BOND,NHAI 54EC Capital Gain Bond,500,2024-06-01,10000.00,10000.00,54EC tax saving
pms,ASK_IEP,ASK Investment Managers - IEP,1,2023-04-01,5000000.00,5800000.00,Premium equity PMS
gold,GOLDBEES,Nippon Gold ETF,1000,2023-01-15,48.00,,Gold ETF
gold,GOLD_PHYSICAL,Physical Gold 24K (grams),30,2020-06-01,4500.00,7200.00,30 grams
real_estate,PROP_MUM_COMM,Commercial Office Andheri Mumbai,1,2020-01-01,18000000.00,24000000.00,Rented - 6% yield
insurance,HDFC_ULIP,HDFC Life ProGrowth Plus ULIP,1,2021-01-01,1500000.00,1850000.00,10 year plan
insurance,ICICI_TERM,ICICI Pru iProtect Smart Term Plan,1,2022-01-01,350000.00,350000.00,1 Cr cover""",

    "Mr. Arjun Kapoor": """asset_class,symbol_or_id,description,quantity,acquisition_date,acquisition_price,current_price,notes
equity,TCS,Tata Consultancy Services,500,2021-06-15,3100.00,,IT core
equity,INFY,Infosys Ltd,600,2021-09-01,1550.00,,IT
equity,WIPRO,Wipro Ltd,1000,2022-01-10,650.00,,IT
equity,HCLTECH,HCL Technologies,400,2022-03-15,1100.00,,IT
equity,TECHM,Tech Mahindra,500,2022-06-01,1050.00,,IT
equity,ZOMATO,Zomato Ltd,5000,2023-01-15,55.00,,New age tech
equity,PAYTM,One97 Communications (Paytm),2000,2023-06-01,800.00,,Digital payments
equity,ADANIENT,Adani Enterprises,200,2023-03-01,2200.00,,Infra conglomerate
equity,RELIANCE,Reliance Industries,150,2022-06-01,2500.00,,Diversified
equity,BAJFINANCE,Bajaj Finance,100,2022-09-01,7000.00,,NBFC
mutual_fund,120503,SBI Small Cap Fund - Growth,10000,2022-01-10,105.00,,Small cap
mutual_fund,118989,Nippon India Small Cap Fund - Growth,8000,2022-04-01,85.00,,Small cap
mutual_fund,101539,Kotak Emerging Equity Fund - Growth,6000,2022-07-01,72.00,,Mid cap
mutual_fund,143316,Quant Small Cap Fund - Growth,5000,2023-01-15,150.00,,Quant small cap
crypto,bitcoin,Bitcoin,1.50,2023-06-15,2200000.00,,Long term hold
crypto,ethereum,Ethereum,15.00,2023-09-01,135000.00,,DeFi exposure
crypto,solana,Solana,200,2024-01-10,8500.00,,High conviction
pms,MARCELLUS_CCP,Marcellus Consistent Compounders,1,2023-01-01,5000000.00,6200000.00,Quality PMS
aif,UNIFI_BLEND,Unifi Capital Blended Finance,1,2023-07-01,10000000.00,11200000.00,Cat III AIF
gold,GOLDBEES,Nippon Gold ETF,500,2023-06-01,52.00,,Small gold allocation
other,UNLISTED_SWIGGY,Swiggy (Pre-IPO),500,2024-01-15,380.00,520.00,Pre-IPO allocation
other,UNLISTED_BOAT,boAt Lifestyle (Pre-IPO),1000,2023-09-01,450.00,380.00,Pre-IPO allocation""",

    "Sharma Family Office (Principal)": """asset_class,symbol_or_id,description,quantity,acquisition_date,acquisition_price,current_price,notes
equity,RELIANCE,Reliance Industries Ltd,1000,2019-06-15,1250.00,,Core holding
equity,HDFCBANK,HDFC Bank Ltd,1500,2019-09-01,1150.00,,Banking anchor
equity,TCS,Tata Consultancy Services,400,2020-03-20,1800.00,,COVID dip buy
equity,BAJFINANCE,Bajaj Finance Ltd,300,2020-04-01,2800.00,,NBFC
equity,TITAN,Titan Company Ltd,400,2020-06-01,1100.00,,Consumer
equity,INFY,Infosys Ltd,500,2021-01-15,1350.00,,IT
equity,BHARTIARTL,Bharti Airtel,600,2021-06-01,550.00,,Telecom
equity,SBIN,State Bank of India,2000,2021-09-01,420.00,,PSU bank
equity,KOTAKBANK,Kotak Mahindra Bank,400,2021-03-15,1700.00,,Banking
equity,MARUTI,Maruti Suzuki India,100,2022-01-10,7500.00,,Auto
equity,ASIANPAINT,Asian Paints Ltd,200,2022-04-01,3200.00,,Consumer
equity,NESTLEIND,Nestle India Ltd,50,2022-06-15,18000.00,,FMCG
equity,SUNPHARMA,Sun Pharmaceutical,400,2022-09-01,900.00,,Pharma
equity,LT,Larsen & Toubro,200,2022-11-01,2100.00,,Infra
equity,NTPC,NTPC Ltd,1000,2023-01-15,165.00,,Power
equity,POWERGRID,Power Grid Corporation,1500,2023-03-01,225.00,,Utilities
equity,ADANIPORTS,Adani Ports & SEZ,500,2023-06-01,750.00,,Logistics
equity,DMART,Avenue Supermarts,100,2023-01-10,4200.00,,Retail
equity,WIPRO,Wipro Ltd,500,2023-04-01,400.00,,IT
equity,ITC,ITC Ltd,2000,2020-01-15,240.00,,Dividend + FMCG
mutual_fund,119598,SBI Blue Chip Fund - Growth,20000,2020-01-10,42.00,,Large cap SIP
mutual_fund,100356,Mirae Asset Large Cap Fund - Growth,15000,2020-06-01,58.00,,Large cap
mutual_fund,122639,Parag Parikh Flexi Cap Fund - Growth,12000,2021-01-15,38.00,,Flexi cap
mutual_fund,102885,Kotak Flexicap Fund - Growth,10000,2021-06-01,48.00,,Flexi cap
mutual_fund,119816,Axis Midcap Fund - Growth,8000,2022-01-10,58.00,,Mid cap
mutual_fund,105506,DSP Midcap Fund - Growth,6000,2022-04-01,82.00,,Mid cap
mutual_fund,120503,SBI Small Cap Fund - Growth,5000,2022-07-01,98.00,,Small cap
mutual_fund,100173,Axis Long Term Equity Fund - Growth,15000,2021-03-20,58.00,,ELSS
mutual_fund,100475,HDFC Balanced Advantage Fund - Growth,10000,2021-09-01,280.00,,BAF
mutual_fund,100484,HDFC Multi Asset Fund - Growth,8000,2022-06-01,42.00,,Multi asset
mutual_fund,118639,Motilal Oswal Nasdaq 100 FoF - Growth,5000,2023-01-15,22.00,,US tech exposure
mutual_fund,100467,HDFC Liquid Fund - Growth,50000,2024-01-01,4200.00,,Parking
real_estate,PROP_DEL_01,Farmhouse Chattarpur Delhi,1,2015-06-01,60000000.00,85000000.00,10 acre farmhouse
real_estate,PROP_GOA_01,Villa Anjuna Goa,1,2019-01-01,25000000.00,38000000.00,Vacation property
real_estate,PROP_BLR_COMM,Commercial Office Whitefield Bangalore,1,2020-06-01,35000000.00,42000000.00,Rented - 7% yield
fd,SBI_FD_1YR,SBI Fixed Deposit 1 Year,8000000,2025-01-01,1.00,1.00,7.1% p.a.
fd,HDFC_FD_2YR,HDFC Bank FD 2 Year,5000000,2024-06-01,1.00,1.00,7.25% p.a.
bond,NHAI_54EC,NHAI 54EC Capital Gain Bond,1000,2023-06-01,10000.00,10000.00,54EC
bond,REC_NCD,REC Ltd NCD 7.8% 2027,500,2024-01-15,1000.00,1010.00,PSU bond
pms,ASK_IEP,ASK Investment Managers - IEP,1,2022-01-01,10000000.00,13500000.00,Premium PMS
pms,MARCELLUS_CCP,Marcellus Consistent Compounders,1,2022-06-01,10000000.00,12800000.00,Quality PMS
aif,KOTAK_SPECIAL_SIT,Kotak Special Situations Fund,1,2023-01-01,15000000.00,17500000.00,Cat II AIF
gold,GOLD_PHYSICAL,Physical Gold 24K (grams),500,2018-06-01,3000.00,7200.00,Family gold
gold,SGB_2027,Sovereign Gold Bond 2027-28,200,2022-10-01,5200.00,7100.00,200 units SGB
gold,GOLDBEES,Nippon Gold ETF,3000,2023-01-15,48.00,,Gold ETF
insurance,LIC_JEEVAN_UMANG,LIC Jeevan Umang Whole Life,1,2018-01-01,2500000.00,3200000.00,Whole life plan
insurance,HDFC_CLICK2PROTECT,HDFC Life Click2Protect 3D Plus,1,2020-06-01,500000.00,500000.00,2 Cr term cover
insurance,SBI_LIFE_SMART,SBI Life Smart Wealth Builder,1,2021-01-01,1800000.00,2200000.00,ULIP""",

    "Ms. Ananya Bhat": """asset_class,symbol_or_id,description,quantity,acquisition_date,acquisition_price,current_price,notes
equity,TCS,Tata Consultancy Services,200,2022-06-15,3200.00,,ESG-compliant IT
equity,INFY,Infosys Ltd,300,2022-09-01,1500.00,,ESG-compliant IT
equity,WIPRO,Wipro Ltd,400,2023-01-10,400.00,,ESG-compliant IT
equity,TATAPOWER,Tata Power Company,1000,2023-03-15,220.00,,Green energy transition
equity,ADANIGREEN,Adani Green Energy,300,2023-06-01,1200.00,,Renewable energy
equity,HINDUNILVR,Hindustan Unilever,100,2022-04-01,2400.00,,ESG leader
equity,TATAMOTORS,Tata Motors Ltd,500,2023-01-15,400.00,,EV transition play
equity,RELIANCE,Reliance Industries,100,2023-09-01,2500.00,,Green hydrogen bet
mutual_fund,112324,Axis Bluechip Fund - Growth,8000,2022-01-10,42.00,,Large cap ESG-friendly
mutual_fund,119598,SBI Blue Chip Fund - Growth,6000,2022-06-01,56.00,,Large cap
mutual_fund,120387,Mirae Asset Tax Saver Fund - Growth,5000,2022-03-15,32.00,,ELSS
mutual_fund,122639,Parag Parikh Flexi Cap Fund - Growth,4000,2023-01-15,48.00,,Global diversification
mutual_fund,143471,DSP Global Innovation FoF - Growth,3000,2023-06-01,12.00,,International tech
mutual_fund,119816,Axis Midcap Fund - Growth,3000,2023-09-01,78.00,,Midcap
fd,SBI_GREEN_FD,SBI Green Fixed Deposit 3 Year,3000000,2024-06-01,1.00,1.00,6.8% green deposit
fd,HDFC_FD_1YR,HDFC Bank FD 1 Year,2000000,2025-01-01,1.00,1.00,7.0% p.a.
bond,IREDA_GREEN,IREDA Green Bond 7.5% 2028,200,2024-03-01,1000.00,1015.00,Green bond
gold,SGB_2029,Sovereign Gold Bond 2029-30,80,2024-04-01,6200.00,7100.00,80 units SGB
mutual_fund,118639,Motilal Oswal Nasdaq 100 FoF - Growth,5000,2023-06-01,20.00,,US tech exposure""",

    "Mr. Rajan Pillai": """asset_class,symbol_or_id,description,quantity,acquisition_date,acquisition_price,current_price,notes
equity,RELIANCE,Reliance Industries,500,2022-01-15,2300.00,,Transferred from prev broker
equity,TCS,Tata Consultancy Services,300,2022-03-01,3500.00,,Core IT
equity,HDFCBANK,HDFC Bank Ltd,600,2022-06-01,1350.00,,Banking
equity,INFY,Infosys Ltd,400,2022-09-01,1450.00,,IT
equity,BHARTIARTL,Bharti Airtel,500,2022-11-01,800.00,,Telecom
equity,SBIN,State Bank of India,1000,2023-01-15,550.00,,PSU banking
equity,LT,Larsen & Toubro,200,2023-03-01,2200.00,,Infrastructure
equity,BAJFINANCE,Bajaj Finance,150,2023-06-01,6500.00,,NBFC
equity,SUNPHARMA,Sun Pharmaceutical,300,2023-01-10,1000.00,,Pharma
equity,TITAN,Titan Company,150,2023-04-01,2600.00,,Consumer
equity,NTPC,NTPC Ltd,800,2023-06-15,175.00,,Power
equity,ADANIENT,Adani Enterprises,100,2023-09-01,2400.00,,Diversified
equity,KOTAKBANK,Kotak Mahindra Bank,200,2023-01-01,1800.00,,Banking
equity,MARUTI,Maruti Suzuki,60,2023-03-15,8500.00,,Auto
equity,HINDUNILVR,Hindustan Unilever,80,2023-06-01,2500.00,,FMCG
mutual_fund,100356,Mirae Asset Large Cap Fund - Growth,10000,2022-06-01,72.00,,Large cap
mutual_fund,122639,Parag Parikh Flexi Cap Fund - Growth,8000,2022-09-01,42.00,,Flexi cap
mutual_fund,102885,Kotak Flexicap Fund - Growth,6000,2023-01-15,50.00,,Flexi cap
mutual_fund,119816,Axis Midcap Fund - Growth,5000,2023-04-01,68.00,,Mid cap
mutual_fund,105506,DSP Midcap Fund - Growth,4000,2023-06-01,78.00,,Mid cap
pms,ASK_IEP,ASK Investment Managers - IEP,1,2023-01-01,10000000.00,12000000.00,Premium PMS
pms,IIFL_MULTICAP,IIFL Multicap PMS,1,2023-06-01,8000000.00,9200000.00,Multi cap PMS
aif,KOTAK_INFRA,Kotak Infrastructure & RE Fund,1,2023-04-01,12000000.00,13500000.00,Cat II infra AIF
real_estate,PROP_CHN_01,4BHK Besant Nagar Chennai,1,2018-01-01,35000000.00,48000000.00,Primary residence
real_estate,PROP_BLR_01,3BHK Indiranagar Bangalore,1,2021-06-01,28000000.00,35000000.00,Investment property
fd,SBI_FD_1YR,SBI Fixed Deposit 1 Year,5000000,2025-01-01,1.00,1.00,7.1% p.a.
fd,HDFC_FD_2YR,HDFC Bank FD 2 Year,4000000,2024-06-01,1.00,1.00,7.25% p.a.
bond,NHAI_54EC,NHAI 54EC Capital Gain Bond,500,2024-01-01,10000.00,10000.00,Capital gain saving
gold,GOLDBEES,Nippon Gold ETF,2000,2023-06-01,50.00,,Gold ETF
gold,SGB_2028,Sovereign Gold Bond 2028-29,100,2023-10-01,5800.00,7100.00,100 units
crypto,bitcoin,Bitcoin,0.30,2024-06-01,4500000.00,,Small BTC allocation""",
}


def main():
    print("=" * 60)
    print("  Seeding Client Portfolios")
    print("=" * 60)

    # Get investors
    investors = get("/investor/investors?limit=20")
    if isinstance(investors, dict) and investors.get("error"):
        print(f"ERROR: {investors['error']}")
        sys.exit(1)

    inv_map = {inv["name"]: inv["id"] for inv in investors}
    print(f"Found {len(inv_map)} investors")

    for name, csv_data in PORTFOLIOS.items():
        inv_id = inv_map.get(name)
        if not inv_id:
            print(f"  SKIP: {name} (not found)")
            continue

        print(f"\n  {name} ({inv_id[:8]}...):")
        result = post_csv(f"/portfolio/{inv_id}/import-csv", csv_data)
        if result.get("error"):
            print(f"    ERROR: {result['error'][:100]}")
        else:
            added = result.get("added", 0)
            errors = result.get("errors", [])
            print(f"    Added: {added} holdings")
            if errors:
                for e in errors[:3]:
                    print(f"    Error: {e}")

    # Verify
    print("\n" + "=" * 60)
    print("  VERIFICATION")
    print("=" * 60)
    for name, inv_id in inv_map.items():
        summary = get(f"/portfolio/{inv_id}/summary")
        if summary.get("error"):
            print(f"  {name}: ERROR")
        else:
            ti = summary.get("total_invested", 0)
            cv = summary.get("current_value", 0)
            gl = summary.get("total_gain_loss", 0)
            hc = summary.get("holdings_count", 0)
            ac = summary.get("asset_classes_count", 0)
            print(f"  {name:<40} {hc:>3} holdings | {ac} classes | Invested: {ti:>14,.0f} | Current: {cv:>14,.0f} | G/L: {gl:>+12,.0f}")

    print("=" * 60)


if __name__ == "__main__":
    main()
