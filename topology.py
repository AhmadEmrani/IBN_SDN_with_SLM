from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info

def create_topology():
    setLogLevel('info')
    net = Mininet(controller=RemoteController, switch=OVSKernelSwitch)
    net.addController('c0', controller=RemoteController, ip='172.20.0.10', port=6653)
    s1 = net.addSwitch('s1', protocols='OpenFlow13')
    h1 = net.addHost('h1', ip='10.0.0.1')
    h2 = net.addHost('h2', ip='10.0.0.2')
    h3 = net.addHost('h3', ip='10.0.0.3')
    for h in (h1, h2, h3):
        net.addLink(h, s1)
    net.start()
    info('*** Entering CLI\n')
    try:
        CLI(net)
    finally:
        net.stop()

if __name__ == '__main__':
    create_topology()
