module packet_engine_top(input logic clk, input logic rst_n);
  cfg_regs cfg_regs_i(.clk(clk), .rst_n(rst_n));
  ingress_queue ingress_queue_i(.clk(clk), .rst_n(rst_n));
  packet_parser packet_parser_i(.clk(clk), .rst_n(rst_n));
  checksum_transform checksum_transform_i(.clk(clk), .rst_n(rst_n));
  channel_arbiter channel_arbiter_i(.clk(clk), .rst_n(rst_n));
  egress_queue egress_queue_i(.clk(clk), .rst_n(rst_n));
  irq_status irq_status_i(.clk(clk), .rst_n(rst_n));
endmodule

