from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info

def create_topology():
    setLogLevel('info')
    net = Mininet(controller=RemoteController, switch=OVSKernelSwitch)

    info('*** Adding controller\n')
    # نام کنترلر همان نام سرویس در داکر کامپوز است
    net.addController('c0', controller=RemoteController, ip='172.20.0.10', port=6653)

    info('*** Adding switches\n')
    s1 = net.addSwitch('s1', protocols='OpenFlow13')

    info('*** Adding hosts\n')
    h1 = net.addHost('h1', ip='10.0.0.1')
    h2 = net.addHost('h2', ip='10.0.0.2')
    h3 = net.addHost('h3', ip='10.0.0.3')

    info('*** Creating links\n')
    net.addLink(h1, s1)
    net.addLink(h2, s1)
    net.addLink(h3, s1)

    info('*** Starting network\n')
    net.start()

    info('*** Running CLI (or keeping alive for tests)\n')
    # برای محیط داکر، می‌توانید دستورات تستی خودکار بگذارید یا وارد CLI شوید
    # دستیار: برای اجرای دستورات خودکار پینگ:
    h1.cmd('ping -c 3 10.0.0.2')
    
    # نگه داشتن شبکه باز برای تست‌های دستی
    CLI(net)
    net.stop()

if __name__ == '__main__':
    create_topology()
