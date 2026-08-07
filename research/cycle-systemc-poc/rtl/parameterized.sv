module parameterized #(parameter int WIDTH = 16)
  (input logic [WIDTH-1:0] a, output logic [WIDTH-1:0] y);
  assign y = a + WIDTH'(1);
endmodule

