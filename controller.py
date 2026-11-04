from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER,
    MAIN_DISPATCHER,
    set_ev_cls,
)
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types


class SimpleSwitch13(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13, self).__init__(*args, **kwargs)

        self.mac_to_port = {}

        # Static firewall rules for our first experiment
        self.firewall_rules = [
            {
                "src_ip": "10.0.0.1",
                "dst_ip": "10.0.0.3",
                "action": "DROP",
            },
            {
                "src_ip": "10.0.0.3",
                "dst_ip": "10.0.0.1",
                "action": "DROP",
            },
        ]

    def add_flow(
        self,
        datapath,
        priority,
        match,
        actions,
        buffer_id=None,
    ):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        instructions = [
            parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS,
                actions,
            )
        ]

        kwargs = {
            "datapath": datapath,
            "priority": priority,
            "match": match,
            "instructions": instructions,
        }

        if buffer_id is not None:
            kwargs["buffer_id"] = buffer_id

        mod = parser.OFPFlowMod(**kwargs)

        datapath.send_msg(mod)

    def install_firewall_rules(self, datapath):

        parser = datapath.ofproto_parser

        for rule in self.firewall_rules:

            match = parser.OFPMatch(
                eth_type=0x0800,
                ipv4_src=rule["src_ip"],
                ipv4_dst=rule["dst_ip"],
            )

            # Empty instructions means DROP
            mod = parser.OFPFlowMod(
                datapath=datapath,
                priority=100,
                match=match,
                instructions=[],
            )

            datapath.send_msg(mod)

            self.logger.info(
                "FIREWALL RULE INSTALLED: %s -> %s : DROP",
                rule["src_ip"],
                rule["dst_ip"],
            )

    @set_ev_cls(
        ofp_event.EventOFPSwitchFeatures,
        CONFIG_DISPATCHER,
    )
    def switch_features_handler(self, ev):

        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Default table-miss rule
        match = parser.OFPMatch()

        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_CONTROLLER,
                ofproto.OFPCML_NO_BUFFER,
            )
        ]

        self.add_flow(
            datapath,
            0,
            match,
            actions,
        )

        # Install firewall rules
        self.install_firewall_rules(datapath)

        self.logger.info(
            "Switch connected: datapath_id=%s",
            datapath.id,
        )

    @set_ev_cls(
        ofp_event.EventOFPPacketIn,
        MAIN_DISPATCHER,
    )
    def _packet_in_handler(self, ev):

        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)

        eth = pkt.get_protocol(ethernet.ethernet)

        if eth is None:
            return

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        self.mac_to_port.setdefault(dpid, {})

        # MAC learning
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [
            parser.OFPActionOutput(out_port)
        ]

        if out_port != ofproto.OFPP_FLOOD:

            match = parser.OFPMatch(
                in_port=in_port,
                eth_dst=dst,
                eth_src=src,
            )

            if msg.buffer_id != ofproto.OFP_NO_BUFFER:

                self.add_flow(
                    datapath,
                    1,
                    match,
                    actions,
                    msg.buffer_id,
                )
                return

            else:

                self.add_flow(
                    datapath,
                    1,
                    match,
                    actions,
                )

        data = None

        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        )

        datapath.send_msg(out)
