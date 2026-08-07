module comb(input logic [15:0] a, b, input logic select,
            output logic [15:0] y);
  always_comb y = select ? (a + b) : (a ^ b);
endmodule

