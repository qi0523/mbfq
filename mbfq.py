import os
from typing import List
import time

class VM:
    PF_NAME = ""
    VF_NAME = ""
    VF_NO = "1"
    TX_BYETS = -1
    SR = 0      # send rate
    AR = -1      # allocated rate
    TR = 0      # target rate
    RU = 0      # 迭代次数
    MG = 0      # 最小带宽保证
    W  = 1     # weight
    NR = 0      # 新分配的速率
    BelowTR = False
    Below_85_Percent_AR = 0  # 连续低于85%的次数

    def __init__(self, pf_name: str, vf_name: str, vf_no: str, mg: int) -> None:
        self.PF_NAME = pf_name
        self.VF_NAME = vf_name
        self.VF_NO = vf_no
        self.MG = mg
        self.fi_tx_bytes = open("/sys/class/net/" + self.VF_NAME + "/statistics/tx_bytes")
        self.TX_BYETS = int(self.fi_tx_bytes.read())
        self.fi_tx_bytes.seek(0, 0)
        self.fi_set_max_tx_rate = open("/sys/class/net/" + self.PF_NAME + "/device/sriov/" + self.VF_NO + "/max_tx_rate", "w")

    def __del__(self) -> None:
        self.fi_tx_bytes.close()
        self.fi_set_max_tx_rate.close()

def collect(NETWORK_CAPACITY: int, vm_list: List[VM], MBFQ_PERIOD):
    used = 0
    for vm in vm_list:
        cur_bytes = int(vm.fi_tx_bytes.read())
        vm.fi_tx_bytes.seek(0, 0)

        vm.SR = (cur_bytes - vm.TX_BYETS) * 8 / MBFQ_PERIOD / (1000 * 1000)
        vm.TX_BYETS = cur_bytes

        used += vm.SR
    return used / NETWORK_CAPACITY

#phase1
def compute_target_rates(NETWORK_CAPACITY: int, vm_list: List[VM]):
    avail_bw_all = NETWORK_CAPACITY
    vm_count_all = 0
    w_all = 0.0
    for vm in vm_list:
        if vm.AR <= 0:
            vm.TR = 1.1 * vm.SR
        if vm.SR < 0.85 * vm.AR and vm.Below_85_Percent_AR >= 4:
            vm.Below_85_Percent_AR += 1
            vm.TR = 1.1 * vm.SR
            vm.RU = max(0, vm.RU - 1)
        elif vm.SR > 0.95 * vm.AR:
            vm.Below_85_Percent_AR = 0
            vm.RU = min(3, vm.RU + 1)
            if vm.RU == 1:
                vm.TR = min(1.2 * vm.AR, vm.AR + 0.1 * NETWORK_CAPACITY)
            elif vm.RU == 2:
                vm.TR = min(1.5 * vm.AR, vm.AR + 0.1 * NETWORK_CAPACITY)
            elif vm.RU == 3:
                vm.TR = max(2 * vm.AR, vm.MG)
        else:
            vm.Below_85_Percent_AR = 0
            vm.TR = vm.AR
            vm.RU = max(0, vm.RU - 1)
        
        vm.TR = max(vm.TR, 10)
        vm.NR = min(vm.TR, vm.MG)

        if vm.NR < vm.TR:
            vm.BelowTR = True
            w_all = w_all + vm.W
            vm_count_all += 1
        else:
            vm.BelowTR = False
        vm.AR = vm.NR
        avail_bw_all -= vm.NR
    return avail_bw_all, vm_count_all, w_all

#phase2
def allocate_sharing_rates(avail_bw_all, vm_count_all, w_all, vm_list: List[VM]):
    while avail_bw_all > 0 and vm_count_all > 0:
        w_all = 0.0
        for vm in vm_list:
            if vm.BelowTR:
                fair_share = avail_bw_all * vm.W / w_all
                vm.NR += fair_share
            if vm.NR >= vm.TR:
                avail_bw_all += (vm.NR - vm.TR)
                vm.NR = vm.TR
                vm.BelowTR = False
                w_all -= vm.W
                vm_count_all -= 1
            vm.AR = vm.NR

def micro_scheduler(vm_list: List[VM], activated_mbfq = True):
    if activated_mbfq:
        for vm in vm_list:
            vm.fi_set_max_tx_rate.seek(0, 0)
            vm.fi_set_max_tx_rate.truncate()
            vm.fi_set_max_tx_rate.write(str(vm.NR))
    else:
        return

def macro_scheduler(NETWORK_CAPACITY, vm_list):

    #phase1: target rate
    avail_bw_all, vm_count_all, w_all = compute_target_rates(NETWORK_CAPACITY, vm_list)

    #phase2: Fair Sharing
    allocate_sharing_rates(avail_bw_all, vm_count_all, w_all, vm_list)
    
    return

def mbfq(NETWORK_CAPACITY, vm_list: List[VM] , activated_mbfq, MBFQ_PERIOD):
    network_utilization = collect(NETWORK_CAPACITY, vm_list, MBFQ_PERIOD)
    # if network_utilization < 0.8:
    #     if activated_mbfq:
    #         #取消限制
    #         activated_mbfq = False
    #         micro_scheduler(vm_list, activated_mbfq)
    #         return activated_mbfq
    #     return activated_mbfq
    # activated_mbfq = True
    macro_scheduler(NETWORK_CAPACITY, vm_list)
    micro_scheduler(vm_list, activated_mbfq)
    return activated_mbfq

def main():
    MBFQ_PERIOD = 0.1
    NETWORK_CAPACITY = 35 * 1000
    activated_mbfq = True
    vm_list = [VM("enp0s3", "", "1", 500)]
    while True:
       time.sleep(MBFQ_PERIOD)
       activated_mbfq = mbfq(NETWORK_CAPACITY, vm_list, activated_mbfq, MBFQ_PERIOD)

if __name__ == "__main__":
    main()