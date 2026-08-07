module child(input logic [15:0] a, output logic [15:0] y);
  assign y = a + 16'd1;
endmodule

module hierarchy(input logic [15:0] a, output logic [15:0] y);
  logic [15:0] middle;
  child first(.a(a), .y(middle));
  child second(.a(middle), .y(y));
endmodule

